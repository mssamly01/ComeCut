# modules/extractor/subtitle_fixer.py

import pysrt
import cv2
import os
import shutil
import numpy as np
import difflib
from tqdm import tqdm
import threading
import time
import gc
import tempfile
from queue import Queue
import psutil

try:
    from skimage.metrics import structural_similarity as ssim
except ImportError:
    # Xử lý trường hợp scikit-image chưa được cài đặt
    print("Cảnh báo: Thư viện 'scikit-image' chưa được cài đặt. Chức năng so sánh khung hình nâng cao sẽ bị ảnh hưởng.")
    print("Vui lòng chạy: pip install scikit-image")
    ssim = None

# Import các thành phần từ VSE
from .VSE_MODULE.backend.tools.ocr import OcrRecogniser
# Import DictionaryManager để sửa lỗi từ điển
from .dictionary_manager import DictionaryManager

class SubtitleFixer:
    """
    Lớp này chứa logic để tìm và sửa các khoảng trống trong file phụ đề
    bằng cách trích xuất khung hình và chạy OCR.
    Phiên bản này sử dụng thuật toán nâng cao để xác định timing chính xác.
    Hỗ trợ sửa lỗi tự động bằng từ điển cho tên nhân vật, địa danh, chiêu thức.
    Đã được tối ưu hóa để xử lý video dài mà không bị đơ.
    """
    def __init__(self, video_path, srt_path, subtitle_area, gap_threshold_frames=5, dictionary_name=None, detection_sensitivity=0.85, progress_callback=None):
        """
        Khởi tạo SubtitleFixer.

        Args:
            video_path (str): Đường dẫn đến file video.
            srt_path (str): Đường dẫn đến file SRT tạm thời để đọc.
            subtitle_area (tuple): Tọa độ (ymin, ymax, xmin, xmax) của vùng phụ đề.
            gap_threshold_frames (int): Ngưỡng số frame để xác định một khoảng trống.
            dictionary_name (str, optional): Tên từ điển sửa lỗi cần áp dụng.
            detection_sensitivity (float): Ngưỡng độ nhạy phát hiện (0.90-0.99, mặc định 0.85).
            progress_callback (callable, optional): Hàm callback để cập nhật tiến trình.
        """
        self.video_path = video_path
        self.srt_path = srt_path
        self.subtitle_area = subtitle_area # (ymin, ymax, xmin, xmax)
        self.detection_sensitivity = detection_sensitivity  # Ngưỡng phát hiện có thể tùy chỉnh
        self.progress_callback = progress_callback  # Callback để cập nhật tiến trình
        
        self.video_cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        self.fps = self.video_cap.get(cv2.CAP_PROP_FPS)
        
        # Tối ưu hóa memory và performance
        self.memory_threshold = 80  # % memory usage threshold
        self.batch_size = 50  # Số frame xử lý mỗi batch
        self.processing_queue = Queue()
        self.results_queue = Queue()
        self.stop_processing = threading.Event()
        
        if self.fps and self.fps > 0:
            self.gap_threshold_ms = (gap_threshold_frames / self.fps) * 1000
        else:
            self.fps = 25 # Giá trị mặc định nếu không đọc được FPS
            self.gap_threshold_ms = (gap_threshold_frames / self.fps) * 1000
            print(f"Cảnh báo: Không thể đọc FPS từ video. Sử dụng giá trị mặc định là {self.fps}.")

        print("Đang khởi tạo PaddleOCR Engine cho Subtitle Fixer...")
        self.ocr = OcrRecogniser()
        print("PaddleOCR Engine đã sẵn sàng.")
        
        # Khởi tạo DictionaryManager và tải từ điển nếu có
        self.dictionary_manager = DictionaryManager()
        self.dictionary_name = dictionary_name
        if dictionary_name:
            if self.dictionary_manager.load_dictionary(dictionary_name):
                print(f"Đã tải từ điển sửa lỗi: {dictionary_name}")
            else:
                print(f"Không tìm thấy từ điển: {dictionary_name}. Sẽ không áp dụng sửa lỗi tự động.")
                self.dictionary_name = None

        # Thư mục tạm riêng để debug, tránh đụng vào Pictures/Screenshots của hệ thống
        try:
            self.screenshot_dir = tempfile.mkdtemp(prefix="subtitle_extractor_screenshots_")
        except Exception as e:
            print(f"Cảnh báo: Không tạo được thư mục debug tạm: {e}")
            self.screenshot_dir = None
    
    def _check_memory_usage(self):
        """Kiểm tra sử dụng memory và giải phóng nếu cần."""
        try:
            memory_percent = psutil.virtual_memory().percent
            if memory_percent > self.memory_threshold:
                print(f"⚠️ Memory usage cao ({memory_percent:.1f}%), đang giải phóng...")
                gc.collect()
                time.sleep(0.1)  # Nghỉ ngắn để hệ thống giải phóng memory
                return True
        except Exception as e:
            print(f"Lỗi khi kiểm tra memory: {e}")
        return False
    
    def _update_progress(self, current, total, message=""):
        """Cập nhật tiến trình xử lý."""
        if self.progress_callback:
            try:
                progress_percent = (current / total) * 100 if total > 0 else 0
                self.progress_callback(progress_percent, message)
            except Exception as e:
                print(f"Lỗi khi cập nhật tiến trình: {e}")
    

    def _get_frame_at_ms(self, ms):
        """Lấy một khung hình tại một mốc thời gian mili giây cụ thể."""
        self.video_cap.set(cv2.CAP_PROP_POS_MSEC, ms)
        ret, frame = self.video_cap.read()
        return frame if ret else None

    def _compare_frames(self, frame1, frame2, precise_area=None):
        """So sánh sự khác biệt của hai khung hình trong vùng phụ đề (hoặc vùng precise_area nếu có)."""
        if frame1 is None or frame2 is None: return 0
        
        ymin_base, ymax_base, xmin_base, xmax_base = self.subtitle_area
        
        # Hàm tiền xử lý để tách chữ khỏi nền
        def preprocess(roi):
            if roi.size == 0: return None
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            _, thresh = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
            kernel = np.ones((2, 2), np.uint8)
            return cv2.dilate(thresh, kernel, iterations=1)
        
        # Nếu có precise_area (từ OCR), sử dụng Template Matching để chống rung/di chuyển
        if precise_area:
            p_ymin, p_ymax, p_xmin, p_xmax = precise_area
            
            # 1. Trích xuất Template từ frame1 (Vùng chữ chính xác)
            t_ymin, t_ymax = ymin_base + p_ymin, ymin_base + p_ymax
            t_xmin, t_xmax = xmin_base + p_xmin, xmin_base + p_xmax
            template_roi = frame1[t_ymin:t_ymax, t_xmin:t_xmax]
            
            # 2. Trích xuất Search Area từ frame2 (Vùng mở rộng để dò tìm)
            s_padding = 10
            s_ymin = max(0, t_ymin - s_padding)
            s_ymax = min(frame2.shape[0], t_ymax + s_padding)
            s_xmin = max(0, t_xmin - s_padding)
            s_xmax = min(frame2.shape[1], t_xmax + s_padding)
            search_roi = frame2[s_ymin:s_ymax, s_xmin:s_xmax]
            
            if template_roi.size == 0 or search_roi.size == 0:
                return 1.0
            
            if search_roi.shape[0] < template_roi.shape[0] or search_roi.shape[1] < template_roi.shape[1]:
                return 0.0
                
            try:
                t_processed = preprocess(template_roi)
                s_processed = preprocess(search_roi)
                
                # Sử dụng Template Matching (Correlation Coefficient Normed)
                # Đây là phương pháp cực kỳ ổn định để tìm kiếm một mẫu trong một vùng nhỏ (chống rung)
                res = cv2.matchTemplate(s_processed, t_processed, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                return max_val
            except Exception:
                return 0.0
        
        # Fallback về phương pháp so sánh trực tiếp nếu không có precise_area
        ymin, ymax = max(0, int(ymin_base)), min(frame1.shape[0], int(ymax_base))
        xmin, xmax = max(0, int(xmin_base)), min(frame1.shape[1], int(xmax_base))
        
        roi1 = frame1[ymin:ymax, xmin:xmax]
        roi2 = frame2[ymin:ymax, xmin:xmax]
        
        if roi1.size == 0 or roi2.size == 0:
            return 1.0
            
        try:
            t1 = preprocess(roi1)
            t2 = preprocess(roi2)
            
            if t1 is None or t2 is None: return 1.0
            
            if ssim is not None:
                min_side = min(t1.shape[0], t1.shape[1])
                w_size = 7
                if min_side < 7:
                    w_size = min_side if min_side % 2 != 0 else min_side - 1
                
                if w_size >= 3:
                    score, _ = ssim(t1, t2, full=True, win_size=w_size)
                else:
                    diff = cv2.absdiff(t1, t2)
                    score = 1.0 - (np.sum(diff) / (t1.size * 255.0))
            else:
                diff = cv2.absdiff(t1, t2)
                score = 1.0 - (np.sum(diff) / (t1.size * 255.0))
                
            return score
        except Exception:
            return 1.0

    def _find_precise_boundaries(self, middle_ms, min_ms, max_ms, precise_area=None):
        """
        Tinh chỉnh ranh giới start/end của một cụm phụ đề bằng SSIM + binary search.
        Dùng SSIM (so sánh kết cấu ảnh) để phân biệt chính xác khi phụ đề thay đổi hoặc biến mất.
        Nhanh hơn quét tuyến tính nhờ binary search.
        """
        if not self.video_cap.isOpened():
            self.video_cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)

        frame_ms = 1000.0 / self.fps
        base_frame = self._get_frame_at_ms(middle_ms)
        if base_frame is None:
            return min_ms, max_ms

        def is_same_sub(ms):
            """Trả về True nếu frame tại ms chứa cùng phụ đề với base_frame."""
            f = self._get_frame_at_ms(ms)
            return self._compare_frames(base_frame, f, precise_area) >= self.detection_sensitivity

        # Binary search tìm điểm bắt đầu
        if is_same_sub(min_ms):
            start_bound = min_ms
        else:
            lo, hi = min_ms, middle_ms
            while hi - lo > frame_ms * 2:
                mid = (lo + hi) / 2
                if is_same_sub(mid):
                    hi = mid
                else:
                    lo = mid
            start_bound = hi

        # Binary search tìm điểm kết thúc
        if is_same_sub(max_ms):
            end_bound = max_ms
        else:
            lo, hi = middle_ms, max_ms
            while hi - lo > frame_ms * 2:
                mid = (lo + hi) / 2
                if is_same_sub(mid):
                    lo = mid
                else:
                    hi = mid
            end_bound = lo

        return max(min_ms, start_bound), min(max_ms, end_bound)


    def ocr_and_create_subs(self, sub_periods):
        """Chạy OCR và tạo các đối tượng SubRipItem. KHÔNG áp dụng sửa lỗi từ điển trong quá trình OCR."""
        new_subs = []
        for period in tqdm(sub_periods, desc="  - Đang OCR các vùng tìm thấy", leave=False, ncols=100):
            start_ms, end_ms = period['start_ms'], period['end_ms']
            
            ocr_frame = self._get_frame_at_ms((start_ms + end_ms) / 2)
            if ocr_frame is None: continue

            ymin, ymax, xmin, xmax = self.subtitle_area
            cropped_frame = ocr_frame[ymin:ymax, xmin:xmax]
            
            _, rec_res = self.ocr.predict(cropped_frame)

            if rec_res:
                full_text = " ".join([res[0] for res in rec_res if res[1] > 0.8])
                if full_text.strip():
                    # KHÔNG áp dụng sửa lỗi từ điển trong quá trình OCR
                    # Từ điển chỉ được áp dụng khi bấm nút "Kiểm tra phụ đề"
                    print(f"  - Tìm thấy text: '{full_text}' @ {int((start_ms+end_ms)/2)}ms")
                    new_sub = pysrt.SubRipItem(
                        index=0,
                        start=pysrt.SubRipTime.from_ordinal(start_ms),
                        end=pysrt.SubRipTime.from_ordinal(end_ms),
                        text=full_text
                    )
                    new_subs.append(new_sub)
        return new_subs

    def _has_subtitle_pixels(self, frame):
        """
        Kiểm tra nhanh xem frame có chứa pixel chữ trong vùng subtitle_area không.
        Dùng threshold đơn giản - cực kỳ nhanh, không cần OCR.
        """
        if frame is None:
            return False
        ymin, ymax, xmin, xmax = self.subtitle_area
        roi = frame[ymin:ymax, xmin:xmax]
        if roi.size == 0:
            return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Chỉ cần đếm pixel sáng (chữ trắng/vàng) - nhanh hơn dùng 2 threshold
        bright_count = np.count_nonzero(gray > 200)
        # Ngưỡng: ít nhất 0.5% pixel sáng (tương đương ~vài chục pixel chữ)
        return bright_count > (gray.size * 0.005)

    def _binary_search_boundary(self, has_text_ms, no_text_ms, direction='start'):
        """
        Dùng binary search để tìm chính xác ranh giới bắt đầu/kết thúc của cụm phụ đề.
        Thay vì quét tuyến tính từng frame, binary search chỉ cần log2(N) bước.
        
        direction='start': has_text_ms < no_text_ms  (tìm điểm bắt đầu)
        direction='end':   no_text_ms < has_text_ms  (tìm điểm kết thúc)
        """
        frame_ms = 1000.0 / self.fps
        lo, hi = min(has_text_ms, no_text_ms), max(has_text_ms, no_text_ms)
        
        while hi - lo > frame_ms * 2:
            mid = (lo + hi) / 2
            frame = self._get_frame_at_ms(mid)
            mid_has_text = self._has_subtitle_pixels(frame)
            
            if direction == 'start':
                # Đang tìm điểm bắt đầu: has_text ở bên phải, no_text ở bên trái
                if mid_has_text:
                    hi = mid  # Ranh giới có thể ở bên trái hơn nữa
                else:
                    lo = mid  # Ranh giới ở bên phải hơn
            else:
                # Đang tìm điểm kết thúc: has_text ở bên trái, no_text ở bên phải
                if mid_has_text:
                    lo = mid  # Ranh giới có thể ở bên phải hơn nữa
                else:
                    hi = mid  # Ranh giới ở bên trái hơn
        
        return (lo + hi) / 2

    def _scan_gap_for_clusters(self, start_ms, end_ms):
        """
        Quét 2 giai đoạn để tìm tất cả cụm phụ đề trong khoảng trống.
        
        Giai đoạn 1 - Coarse Scan (quét thô, bước lớn):
            Nhảy bước lớn (15 frame) để phát hiện nhanh vùng nào có chữ.
            Gap không có phụ đề sẽ bị loại ngay sau bước này → tiết kiệm thời gian.

        Giai đoạn 2 - Fine Scan + Binary Search (chỉ trong vùng đã phát hiện):
            Quét chi tiết (bước nhỏ) trong vùng gần ranh giới để xác định cụm chính xác.
            Dùng binary search để tìm điểm đầu/cuối thay vì quét tuyến tính.
        """
        if not self.video_cap.isOpened():
            self.video_cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)

        frame_ms = 1000.0 / self.fps
        gap_duration = end_ms - start_ms

        # --- Giai đoạn 1: Coarse Scan ---
        # Bước lớn tỉ lệ với độ dài gap: gap dài thì nhảy xa hơn, tối thiểu 10 frame
        coarse_step = max(frame_ms * 10, gap_duration / 30)
        
        # Quét thô để thu thập danh sách các điểm "hit" (có chữ)
        hit_points = []
        curr_ms = float(start_ms)
        while curr_ms <= end_ms:
            frame = self._get_frame_at_ms(curr_ms)
            if self._has_subtitle_pixels(frame):
                hit_points.append(curr_ms)
            curr_ms += coarse_step

        # Nếu không có điểm hit nào → gap không có phụ đề, trả về ngay
        if not hit_points:
            return []

        # --- Giai đoạn 2: Gộp hit_points thành vùng (region) và tinh chỉnh ---
        # Gộp các hit gần nhau (cách nhau < 3x coarse_step) thành 1 vùng
        merge_threshold = coarse_step * 3
        regions = []
        r_start = hit_points[0]
        r_end = hit_points[0]
        
        for pt in hit_points[1:]:
            if pt - r_end <= merge_threshold:
                r_end = pt
            else:
                regions.append((r_start, r_end))
                r_start = pt
                r_end = pt
        regions.append((r_start, r_end))

        # --- Tinh chỉnh từng vùng bằng Fine Scan + Binary Search ---
        clusters = []
        fine_step = frame_ms * 2  # Bước nhỏ cho fine scan

        for region_start, region_end in regions:
            # Mở rộng vùng tìm kiếm thêm 1 coarse_step ra hai phía để không bỏ sót
            search_start = max(start_ms, region_start - coarse_step)
            search_end = min(end_ms, region_end + coarse_step)

            # Fine scan trong vùng mở rộng để tìm các hit chính xác hơn
            fine_hits = []
            curr_ms = search_start
            while curr_ms <= search_end:
                frame = self._get_frame_at_ms(curr_ms)
                if self._has_subtitle_pixels(frame):
                    fine_hits.append(curr_ms)
                curr_ms += fine_step

            if not fine_hits:
                continue

            # Gộp fine_hits thành sub-clusters (phân tách nếu có khoảng trống > gap_threshold)
            sub_merge_threshold = self.gap_threshold_ms * 0.8
            sub_clusters_raw = []
            sc_start = fine_hits[0]
            sc_end = fine_hits[0]
            
            for pt in fine_hits[1:]:
                if pt - sc_end <= sub_merge_threshold:
                    sc_end = pt
                else:
                    sub_clusters_raw.append((sc_start, sc_end))
                    sc_start = pt
                    sc_end = pt
            sub_clusters_raw.append((sc_start, sc_end))

            # Với mỗi sub-cluster: Binary Search để tìm ranh giới chính xác
            for sc_start_raw, sc_end_raw in sub_clusters_raw:
                # Tìm điểm bắt đầu chính xác
                left_no_text = max(start_ms, sc_start_raw - fine_step * 3)
                precise_start = self._binary_search_boundary(sc_start_raw, left_no_text, direction='start')

                # Tìm điểm kết thúc chính xác
                right_no_text = min(end_ms, sc_end_raw + fine_step * 3)
                precise_end = self._binary_search_boundary(sc_end_raw, right_no_text, direction='end')

                precise_start = max(start_ms, precise_start)
                precise_end = min(end_ms, precise_end)

                # Lọc bỏ cụm quá ngắn (< 2 frame) - có thể là nhiễu
                if precise_end - precise_start < frame_ms * 2:
                    continue

                clusters.append({
                    'start_ms': precise_start,
                    'end_ms': precise_end,
                    'sample_ms': (precise_start + precise_end) / 2
                })

        return clusters

    def _get_cluster_search_window(self, clusters, cluster_index, gap_start_ms, gap_end_ms):
        """
        Mở rộng cửa sổ tìm kiếm cho một cụm subtitle trước khi refine bằng template matching.
        Việc này tránh trường hợp coarse/fine scan cắt mất vài frame đầu/cuối, khiến timestamp
        cuối cùng bị lệch so với hard sub thực tế trên video.
        """
        cluster = clusters[cluster_index]
        frame_ms = 1000.0 / self.fps
        padding_ms = max(frame_ms * 4, 120.0)

        if cluster_index > 0:
            prev_cluster = clusters[cluster_index - 1]
            search_start = (prev_cluster['end_ms'] + cluster['start_ms']) / 2.0
        else:
            search_start = gap_start_ms

        if cluster_index < len(clusters) - 1:
            next_cluster = clusters[cluster_index + 1]
            search_end = (cluster['end_ms'] + next_cluster['start_ms']) / 2.0
        else:
            search_end = gap_end_ms

        search_start = max(gap_start_ms, search_start - padding_ms)
        search_end = min(gap_end_ms, search_end + padding_ms)

        # Đảm bảo sample frame luôn nằm trong cửa sổ refine.
        if search_start >= cluster['sample_ms']:
            search_start = max(gap_start_ms, cluster['start_ms'] - padding_ms)
        if search_end <= cluster['sample_ms']:
            search_end = min(gap_end_ms, cluster['end_ms'] + padding_ms)

        if search_end <= search_start:
            search_start = max(gap_start_ms, cluster['start_ms'] - padding_ms)
            search_end = min(gap_end_ms, cluster['end_ms'] + padding_ms)

        return search_start, search_end

    def _quick_gap_has_text(self, start_ms, end_ms):
        """
        Quét thô cực nhanh để quyết định gap có đáng xử lý chi tiết hay không.
        Mục tiêu là loại nhanh các gap rỗng trước khi vào quy trình scan/OCR đầy đủ.
        """
        if end_ms <= start_ms:
            return False

        if not self.video_cap.isOpened():
            self.video_cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)

        frame_ms = 1000.0 / self.fps
        gap_duration = end_ms - start_ms
        sample_budget = 14
        probe_step = max(frame_ms * 12, gap_duration / sample_budget)

        # Luôn check một vài mốc quan trọng để không bỏ sót chữ xuất hiện ngắn.
        probe_points = [
            start_ms + frame_ms,
            (start_ms + end_ms) / 2.0,
            end_ms - frame_ms
        ]

        curr_ms = start_ms
        while curr_ms <= end_ms:
            probe_points.append(curr_ms)
            curr_ms += probe_step

        checked_slots = set()
        slot_ms = max(frame_ms, 1.0)

        for ms in probe_points:
            clamped_ms = min(end_ms, max(start_ms, ms))
            slot = int(clamped_ms / slot_ms)
            if slot in checked_slots:
                continue
            checked_slots.add(slot)

            frame = self._get_frame_at_ms(clamped_ms)
            if self._has_subtitle_pixels(frame):
                return True

        return False

    def process_gap(self, start_time, end_time, prev_text=None, next_text=None, prev_end_ms=None, next_start_ms=None):
        """
        Xử lý khoảng trống nâng cao: quét toàn bộ gap để tìm TẤT CẢ các cụm phụ đề,
        rồi với mỗi cụm: OCR tại frame giữa của chính cụm đó để đảm bảo
        text luôn khớp với start/end time của khối đó.
        
        Returns:
            list: Danh sách các action cần thực hiện (new_sub, extend_prev, extend_next)
        """
        start_ms, end_ms = start_time.ordinal, end_time.ordinal
        results = []

        # Bước 1: Quét toàn bộ khoảng trống để tìm tất cả cụm frame có chữ
        print(f"    -> Đang quét toàn bộ khoảng trống để tìm cụm phụ đề...")
        clusters = self._scan_gap_for_clusters(start_ms, end_ms)

        if not clusters:
            print(f"    -> Không tìm thấy frame nào có chữ trong khoảng trống này.")
            return results

        print(f"    -> Tìm thấy {len(clusters)} cụm phụ đề tiềm năng.")

        ymin_base, ymax_base, xmin_base, xmax_base = self.subtitle_area

        for cluster_idx, cluster in enumerate(clusters):
            c_start = cluster['start_ms']
            c_end = cluster['end_ms']
            c_sample = cluster['sample_ms']  # frame giữa của chính cụm này
            refine_min_ms, refine_max_ms = self._get_cluster_search_window(
                clusters, cluster_idx, start_ms, end_ms
            )

            # Bước 2: OCR tại frame giữa của CHÍNH cụm này (không phải giữa toàn bộ gap)
            ocr_frame = self._get_frame_at_ms(c_sample)
            if ocr_frame is None:
                continue

            cropped_frame = ocr_frame[ymin_base:ymax_base, xmin_base:xmax_base]
            dt_box, rec_res = self.ocr.predict(cropped_frame)

            if not rec_res:
                continue

            # Tính precise_area từ bounding box OCR của cụm này
            precise_area = None
            if dt_box:
                try:
                    all_x, all_y = [], []
                    for box in dt_box:
                        for pt in box:
                            all_x.append(pt[0])
                            all_y.append(pt[1])
                    if all_x and all_y:
                        p_xmin = max(0, int(min(all_x)) - 5)
                        p_xmax = min(cropped_frame.shape[1], int(max(all_x)) + 5)
                        p_ymin = max(0, int(min(all_y)) - 5)
                        p_ymax = min(cropped_frame.shape[0], int(max(all_y)) + 5)
                        precise_area = (p_ymin, p_ymax, p_xmin, p_xmax)
                except Exception as e:
                    print(f"    -> Lỗi khi tính Precise Area cho cụm {cluster_idx+1}: {e}")

            full_text = " ".join([res[0] for res in rec_res if res[1] > 0.8]).strip()
            if not full_text:
                continue

            # Áp dụng sửa lỗi từ điển
            if self.dictionary_name:
                full_text = self.dictionary_manager.apply_corrections(full_text, self.dictionary_name)

            # Bước 3: Tinh chỉnh ranh giới trong phạm vi của cụm này
            # Dùng cửa sổ đã mở rộng để tránh bị cắt hụt timestamp ở bước scan thô.
            precise_start, precise_end = self._find_precise_boundaries(
                c_sample, refine_min_ms, refine_max_ms, precise_area
            )
            precise_start = int(round(precise_start))
            precise_end = int(round(precise_end))

            if precise_end <= precise_start:
                precise_start = int(round(c_start))
                precise_end = int(round(c_end))

            # Kiểm tra trùng lặp với phụ đề trước/sau bằng cả text + độ gần ranh giới thời gian.
            duplicate_similarity_threshold = 0.9
            duplicate_edge_window_ms = max((1000.0 / self.fps) * 6, 150.0)

            is_duplicate_prev = False
            if prev_text and prev_end_ms is not None:
                similarity = difflib.SequenceMatcher(None, full_text, prev_text).ratio()
                near_prev_edge = abs(precise_start - prev_end_ms) <= duplicate_edge_window_ms
                if similarity > duplicate_similarity_threshold and near_prev_edge:
                    is_duplicate_prev = True

            is_duplicate_next = False
            if next_text and next_start_ms is not None:
                similarity = difflib.SequenceMatcher(None, full_text, next_text).ratio()
                near_next_edge = abs(next_start_ms - precise_end) <= duplicate_edge_window_ms
                if similarity > duplicate_similarity_threshold and near_next_edge:
                    is_duplicate_next = True

            if is_duplicate_prev and is_duplicate_next:
                dist_to_prev = abs(precise_start - prev_end_ms)
                dist_to_next = abs(next_start_ms - precise_end)
                if dist_to_prev <= dist_to_next:
                    is_duplicate_next = False
                else:
                    is_duplicate_prev = False

            if is_duplicate_prev:
                print(f"  - Cụm {cluster_idx+1}: Trùng với phụ đề trước '{full_text}' -> Mở rộng phụ đề trước.")
                results.append({'action': 'extend_prev', 'new_end': precise_end})
                if prev_end_ms is not None:
                    prev_end_ms = max(prev_end_ms, precise_end)
                continue

            if is_duplicate_next:
                print(f"  - Cụm {cluster_idx+1}: Trùng với phụ đề sau '{full_text}' -> Mở rộng phụ đề sau.")
                results.append({'action': 'extend_next', 'new_start': precise_start})
                if next_start_ms is not None:
                    next_start_ms = min(next_start_ms, precise_start)
                continue

            # Tạo phụ đề mới với timing được tinh chỉnh từ chính cụm này
            print(f"  - Cụm {cluster_idx+1}: Tìm thấy phụ đề mới '{full_text}' @ {int(precise_start)}-{int(precise_end)}ms")
            new_sub = pysrt.SubRipItem(
                index=0,
                start=pysrt.SubRipTime.from_ordinal(int(precise_start)),
                end=pysrt.SubRipTime.from_ordinal(int(precise_end)),
                text=full_text
            )
            results.append({'action': 'new_sub', 'item': new_sub})

        return results


    def apply_dictionary_corrections(self, subs):
        """Áp dụng sửa lỗi từ điển cho các phụ đề đã có."""
        if not self.dictionary_name or not subs:
            return subs
            
        corrected_subs = []
        corrections_applied = 0
        
        for sub in subs:
            original_text = sub.text
            corrected_text = self.dictionary_manager.apply_corrections(original_text, self.dictionary_name)
            
            if original_text != corrected_text:
                corrections_applied += 1
                print(f"  - Đã sửa lỗi từ điển: '{original_text}' -> '{corrected_text}'")
                # Tạo phụ đề mới với text đã được sửa
                corrected_sub = pysrt.SubRipItem(
                    index=sub.index,
                    start=sub.start,
                    end=sub.end,
                    text=corrected_text
                )
                corrected_subs.append(corrected_sub)
            else:
                corrected_subs.append(sub)
        
        if corrections_applied > 0:
            print(f"  - Đã áp dụng {corrections_applied} sửa lỗi từ điển")
        
        return corrected_subs
        
    def find_gaps(self, subs):
        """Tìm các khoảng trống thời gian trong file phụ đề dựa trên ngưỡng đã cho."""
        gaps = []
        if not subs: return gaps

        for i in range(len(subs) - 1):
            gap_duration_ms = subs[i+1].start.ordinal - subs[i].end.ordinal
            if gap_duration_ms > self.gap_threshold_ms:
                gaps.append((subs[i].end, subs[i+1].start))
        
        if not self.video_cap.isOpened():
             self.video_cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
        video_duration_ms = self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT) / self.fps * 1000
        last_sub_end_ms = subs[-1].end.ordinal
        if video_duration_ms - last_sub_end_ms > self.gap_threshold_ms:
             end_of_video_time = pysrt.SubRipTime.from_ordinal(video_duration_ms)
             gaps.append((subs[-1].end, end_of_video_time))

        return gaps

    def run(self):
        """Thực thi toàn bộ quy trình vá lỗi phụ đề và trả về đối tượng subs đã cập nhật - Tối ưu hóa cho video dài."""
        try:
            self._update_progress(0, 100, "Đang tải file phụ đề...")
            subs = pysrt.open(self.srt_path, encoding='utf-8')
        except Exception as e:
            print(f"Lỗi: Không thể mở file SRT '{self.srt_path}'. {e}")
            return None

        # Áp dụng sửa lỗi từ điển cho tất cả phụ đề hiện có nếu có từ điển
        if self.dictionary_name:
            self._update_progress(10, 100, f"Đang áp dụng từ điển sửa lỗi '{self.dictionary_name}'...")
            print(f"Đang áp dụng từ điển sửa lỗi '{self.dictionary_name}' cho phụ đề hiện có...")
            subs = self.apply_dictionary_corrections(subs)

        self._update_progress(20, 100, "Đang tìm khoảng trống...")
        gaps = self.find_gaps(subs)
        if not gaps:
            print("Không tìm thấy khoảng trống đáng kể nào. Phụ đề có vẻ đã ổn.")
            self._update_progress(100, 100, "Hoàn thành - Không có khoảng trống")
            return subs
        
        print(f"Tìm thấy {len(gaps)} khoảng trống tiềm năng. Bắt đầu quét chi tiết.")
        
        all_new_subs = []
        total_gaps = len(gaps)
        
        for i, (gap_start, gap_end) in enumerate(gaps):
            if self.stop_processing.is_set():
                print("Đã dừng xử lý theo yêu cầu người dùng.")
                break
                
            progress = 20 + (i / total_gaps) * 70
            self._update_progress(progress, 100, f"Đang xử lý khoảng trống {i+1}/{total_gaps}")
            
            # Tìm context (phụ đề trước/sau khoảng trống)
            prev_sub = None
            next_sub = None
            
            # Tìm chính xác sub bao quanh gap
            p_text = None
            n_text = None
            
            # Duyệt subs để tìm text lân cận
            for s in subs:
                if abs(s.end.ordinal - gap_start.ordinal) < 10:
                    p_text = s.text
                    prev_sub = s
                if abs(s.start.ordinal - gap_end.ordinal) < 10:
                    n_text = s.text
                    next_sub = s

            gap_start_ms = gap_start.ordinal
            gap_end_ms = gap_end.ordinal

            if not self._quick_gap_has_text(gap_start_ms, gap_end_ms):
                print("    -> Quét thô: không thấy chữ trong gap, bỏ qua xử lý chi tiết.")
                continue
            
            print(f"\nĐang xử lý khoảng trống {i+1}/{total_gaps}: từ {gap_start} --> {gap_end}")
            prev_end_ms = prev_sub.end.ordinal if prev_sub else None
            next_start_ms = next_sub.start.ordinal if next_sub else None
            gap_actions = self.process_gap(gap_start, gap_end, p_text, n_text, prev_end_ms, next_start_ms)
            
            for action in gap_actions:
                if action['action'] == 'new_sub':
                    all_new_subs.append(action['item'])
                elif action['action'] == 'extend_prev' and prev_sub:
                    prev_sub.end = pysrt.SubRipTime.from_ordinal(action['new_end'])
                    print(f"    -> Đã mở rộng kết thúc phụ đề trước ({prev_sub.index}) đến {prev_sub.end}")
                elif action['action'] == 'extend_next' and next_sub:
                    next_sub.start = pysrt.SubRipTime.from_ordinal(action['new_start'])
                    print(f"    -> Đã mở rộng bắt đầu phụ đề sau ({next_sub.index}) từ {next_sub.start}")
            
            # Giải phóng memory sau mỗi gap
            gc.collect()
            time.sleep(0.01)

        # Hậu xử lý: Gộp các phụ đề trùng lặp sát nhau
        self._update_progress(95, 100, "Đang tối ưu hóa kết quả cuối cùng...")
        subs.extend(all_new_subs)
        subs.sort(key=lambda x: x.start)
        
        final_subs = []
        if subs:
            curr = subs[0]
            for next_s in subs[1:]:
                # Khoảng cách < 200ms và text cực kỳ giống nhau
                gap = next_s.start.ordinal - curr.end.ordinal
                sim = difflib.SequenceMatcher(None, curr.text, next_s.text).ratio()
                
                if gap < 200 and sim > 0.9:
                    curr.end = next_s.end
                    print(f"  - Gộp phụ đề trùng lặp sau xử lý: '{curr.text[:20]}...'")
                else:
                    final_subs.append(curr)
                    curr = next_s
            final_subs.append(curr)
            subs = pysrt.SubRipFile(final_subs)

        if not all_new_subs:
            print("\nHoàn tất kiểm tra.")
            self._update_progress(100, 100, "Hoàn thành")
            if self.screenshot_dir and os.path.exists(self.screenshot_dir):
                shutil.rmtree(self.screenshot_dir, ignore_errors=True)
                self.screenshot_dir = None
            return subs
        
        # Áp dụng từ điển sửa lỗi cho các phụ đề mới nếu có từ điển
        if self.dictionary_name and all_new_subs:
            print(f"Đang áp dụng từ điển sửa lỗi cho {len(all_new_subs)} phụ đề mới...")
            # Chỉ áp dụng cho các phụ đề mới (all_new_subs)
            corrected_new_subs = self.apply_dictionary_corrections(all_new_subs)
            # Thay thế các phụ đề mới trong danh sách chính
            for i, sub in enumerate(subs):
                if sub in all_new_subs:
                    # Tìm index của sub trong corrected_new_subs
                    # sub có thể không có trong all_new_subs trực tiếp nhưng text và timing khớp
                    for j, c_sub in enumerate(all_new_subs):
                        if c_sub == sub:
                            subs[i] = corrected_new_subs[j]
                            break
        
        for i, sub in enumerate(subs):
            sub.index = i + 1

        print("Quy trình vá lỗi hoàn tất! Đối tượng phụ đề đã được cập nhật.")
        self._update_progress(100, 100, "Hoàn thành - Đã cập nhật phụ đề")
        
        # Cleanup
        if self.screenshot_dir and os.path.exists(self.screenshot_dir):
            shutil.rmtree(self.screenshot_dir, ignore_errors=True)
            self.screenshot_dir = None
            
        if self.video_cap.isOpened():
            self.video_cap.release()
            
        # Giải phóng memory cuối cùng
        gc.collect()
            
        return subs
