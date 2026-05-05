import os
import re
from multiprocessing import Queue, Process
import cv2
from PIL import ImageFont, ImageDraw, Image
from tqdm import tqdm
try:
    from .ocr import OcrRecogniser, get_coordinates
    from .constant import SubtitleArea
    from . import constant
except ImportError as e:
    if 'attempted relative import with no known parent package' not in str(e):
        raise
    from backend.tools.ocr import OcrRecogniser, get_coordinates
    from backend.tools.constant import SubtitleArea
    from backend.tools import constant
from threading import Thread
from shapely.geometry import Polygon
from types import SimpleNamespace
import shutil
import numpy as np
from collections import namedtuple


def extract_subtitles(data, text_recogniser, img, raw_subtitle_file,
                      sub_area, options, dt_box_arg, rec_res_arg, ocr_loss_debug_path, video_path=None, fps=None, invalid_count_ref=None, total_ms=None):
    """
    提取视频帧中的字幕信息
    注意: 已移除置信度和字幕区域检查，接受所有提取的文本
    """
    # 从参数中获取检测框与检测结果
    dt_box = dt_box_arg
    rec_res = rec_res_arg
    # 如果没有检测结果，则获取检测结果
    if dt_box is None or rec_res is None:
        dt_box, rec_res = text_recogniser.predict(img)
        # rec_res格式为： ("hello", 0.997)
    
    # Kiểm tra xem có tìm thấy văn bản không
    if len(dt_box) == 0 or len(rec_res) == 0:
        # Sử dụng total_ms nếu có, nếu không thì dùng frame_no
        if total_ms is not None:
            timestamp = _get_timestamp_from_total_ms(total_ms)
        else:
            timestamp = _get_timestamp_from_frame(data['i'], fps) if fps else f"frame_{data['i']}"
        print(f"Ảnh {timestamp}: OCR không tìm thấy văn bản nào")
        
        # Tăng số lượng ảnh không thể OCR
        if invalid_count_ref is not None:
            invalid_count_ref[0] += 1
        return
    
    # Debug: Hiển thị số lượng văn bản được phát hiện
    # Sử dụng total_ms nếu có, nếu không thì dùng frame_no
    if total_ms is not None:
        timestamp = _get_timestamp_from_total_ms(total_ms)
    else:
        timestamp = _get_timestamp_from_frame(data['i'], fps) if fps else f"frame_{data['i']}"
    print(f"Ảnh {timestamp}: OCR phát hiện {len(dt_box)} vùng văn bản")
    
    # 获取文本坐标
    coordinates = get_coordinates(dt_box)
    # 将结果写入txt文本中
    if options.REC_CHAR_TYPE == 'en':
        # 如果识别语言为英文，则去除中文
        text_res = [(re.sub('[\u4e00-\u9fa5]', '', res[0]), res[1]) for res in rec_res]
    else:
        text_res = [(res[0], res[1]) for res in rec_res]
    line = ''
    loss_list = []
    valid_text_count = 0  # Đếm số văn bản hợp lệ
    
    for i, (content, coordinate) in enumerate(zip(text_res, coordinates)):
        text = content[0]
        prob = content[1]
        print(f"  Văn bản {i+1}: '{text}' (độ tin cậy: {prob:.3f})")
        
        # Kiểm tra xem có đang sử dụng ảnh đã xử lý từ RGBImages không
        # Nếu có, thì toàn bộ ảnh đã là vùng phụ đề, không cần kiểm tra vùng nữa
        use_processed_images = False
        try:
            # Kiểm tra xem có đang sử dụng ảnh từ RGBImages không
            # (Điều này được xác định trong ocr_task_producer)
            rgb_images_dir = os.path.join(os.path.dirname(os.path.dirname(raw_subtitle_file.name)), 'RGBImages')
            use_processed_images = os.path.exists(rgb_images_dir)
        except:
            pass
        
        if use_processed_images:
            # Sử dụng ảnh đã xử lý từ RGBImages - toàn bộ ảnh đã là vùng phụ đề
            print(f"    Sử dụng ảnh đã xử lý - bỏ qua kiểm tra vùng phụ đề")
            # Bỏ kiểm tra độ tin cậy - chấp nhận tất cả văn bản
            selected = True
            valid_text_count += 1
            line += f'{str(data["i"]).zfill(8)}\t{coordinate}\t{text}\n'
            raw_subtitle_file.write(f'{str(data["i"]).zfill(8)}\t{coordinate}\t{text}\n')
            print(f"    ✅ CHẤP NHẬN văn bản này (độ tin cậy: {prob:.3f})")
            
            # 保存丢掉的识别结果
            loss_info = namedtuple('loss_info', 'text prob overflow_area_rate coordinate selected')
            loss_list.append(loss_info(text, prob, 0, coordinate, selected))
        else:
            # Sử dụng ảnh gốc từ video - bỏ kiểm tra vùng phụ đề vì ảnh đã được cắt ra chỉ còn vùng phụ đề
            print(f"    Sử dụng ảnh gốc - bỏ kiểm tra vùng phụ đề vì ảnh đã được cắt ra")
            # Chấp nhận tất cả văn bản từ ảnh gốc
            selected = True
            valid_text_count += 1
            line += f'{str(data["i"]).zfill(8)}\t{coordinate}\t{text}\n'
            raw_subtitle_file.write(f'{str(data["i"]).zfill(8)}\t{coordinate}\t{text}\n')
            print(f"    ✅ CHẤP NHẬN văn bản này")
            
            # 保存丢掉的识别结果
            loss_info = namedtuple('loss_info', 'text prob overflow_area_rate coordinate selected')
            loss_list.append(loss_info(text, prob, 0, coordinate, selected))
    
    # Log chi tiết về kết quả OCR
    # Sử dụng total_ms nếu có, nếu không thì dùng frame_no
    if total_ms is not None:
        timestamp = _get_timestamp_from_total_ms(total_ms)
    else:
        timestamp = _get_timestamp_from_frame(data['i'], fps) if fps else f"frame_{data['i']}"
    if valid_text_count == 0:
        print(f"Ảnh {timestamp}: Không có văn bản hợp lệ được giữ lại")
        # Tăng số lượng ảnh không thể OCR
        if invalid_count_ref is not None:
            invalid_count_ref[0] += 1
    else:
        print(f"Ảnh {timestamp}: Nhận dạng được {valid_text_count} văn bản hợp lệ")
    
    # 输出调试信息
    dump_debug_info(options, line, img, loss_list, ocr_loss_debug_path, sub_area, data)


def dump_debug_info(options, line, img, loss_list, ocr_loss_debug_path, sub_area, data):
    loss = False
    if options.DEBUG_OCR_LOSS and options.REC_CHAR_TYPE in ('ch', 'japan ', 'korea', 'ch_tra'):
        loss = len(line) > 0 and re.search(r'[\u4e00-\u9fa5\u3400-\u4db5\u3130-\u318F\uAC00-\uD7A3\u0800-\u4e00]', line) is None
    if loss:
        if not os.path.exists(ocr_loss_debug_path):
            os.makedirs(ocr_loss_debug_path, mode=0o777, exist_ok=True)
        img = cv2.rectangle(img, (sub_area[2], sub_area[0]), (sub_area[3], sub_area[1]), constant.BGR_COLOR_BLUE, 2)
        for loss_info in loss_list:
            coordinate = loss_info.coordinate
            color = constant.BGR_COLOR_GREEN if loss_info.selected else constant.BGR_COLOR_RED
            text = f"[{loss_info.text}] prob:{loss_info.prob:.4f} or:{loss_info.overflow_area_rate:.2f}"
            img = paint_chinese_opencv(img, text, pos=(coordinate[0], coordinate[2] - 30), color=color)
            img = cv2.rectangle(img, (coordinate[0], coordinate[2]), (coordinate[1], coordinate[3]), color, 2)
        cv2.imwrite(os.path.join(os.path.abspath(ocr_loss_debug_path), f'{str(data["i"]).zfill(8)}.png'), img)


def sub_area_to_polygon(sub_area):
    s_ymin = sub_area[0]
    s_ymax = sub_area[1]
    s_xmin = sub_area[2]
    s_xmax = sub_area[3]
    return Polygon([[s_xmin, s_ymin], [s_xmax, s_ymin], [s_xmax, s_ymax], [s_xmin, s_ymax]])


def coordinate_to_polygon(coordinate):
    xmin = coordinate[0]
    xmax = coordinate[1]
    ymin = coordinate[2]
    ymax = coordinate[3]
    return Polygon([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]])


FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'NotoSansCJK-Bold.otf')
FONT = ImageFont.truetype(FONT_PATH, 20)


def paint_chinese_opencv(im, chinese, pos, color):
    img_pil = Image.fromarray(im)
    fill_color = color  # (color[2], color[1], color[0])
    position = pos
    draw = ImageDraw.Draw(img_pil)
    draw.text(position, chinese, font=FONT, fill=fill_color)
    img = np.asarray(img_pil)
    return img


def _get_timestamp_from_frame(frame_no, fps):
    """Chuyển đổi frame number thành timestamp"""
    if fps is None or fps <= 0:
        return f"frame_{frame_no}"
    
    total_seconds = frame_no / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    milliseconds = int((total_seconds % 1) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def _get_timestamp_from_total_ms(total_ms):
    """Chuyển đổi total_ms thành timestamp (khớp với VSF)"""
    if total_ms is None:
        return "unknown_time"
    
    hours = int(total_ms // (60 * 60 * 1000))
    minutes = int((total_ms % (60 * 60 * 1000)) // (60 * 1000))
    seconds = int((total_ms % (60 * 1000)) // 1000)
    milliseconds = int(total_ms % 1000)
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def ocr_task_consumer(ocr_queue, raw_subtitle_path, sub_area, video_path, options, processed_images=None):
    """
    消费者： 消费ocr_queue，将ocr队列中的数据取出，进行ocr识别，写入字幕文件中
    :param ocr_queue (current_frame_no当前帧帧号, frame 视频帧, dt_box检测框, rec_res识别结果)
    :param raw_subtitle_path
    :param sub_area
    :param video_path
    :param options
    """
    data = {'i': 1}
    # 初始化文本识别对象
    text_recogniser = OcrRecogniser()
    # 丢失字幕的存储路径
    ocr_loss_debug_path = os.path.join(os.path.abspath(os.path.splitext(video_path)[0]), 'loss')
    # 删除之前的缓存垃圾
    if os.path.exists(ocr_loss_debug_path):
        shutil.rmtree(ocr_loss_debug_path, True)

    with open(raw_subtitle_path, mode='w+', encoding='utf-8') as raw_subtitle_file:
        processed_count = 0  # Số ảnh OCR thành công
        invalid_count = [0]  # Đếm số ảnh không thể OCR (sử dụng list để có thể thay đổi trong function)
        total_processed = 0  # Tổng số ảnh đã xử lý (bao gồm cả thành công và lỗi)
        # Lấy FPS từ video để tính timestamp một lần
        cap_temp = cv2.VideoCapture(video_path)
        fps = cap_temp.get(cv2.CAP_PROP_FPS)
        cap_temp.release()
        
        data = {'i': 1}
        while True:
            try:
                frame_no, frame, dt_box, rec_res, total_ms = ocr_queue.get(block=True)
                if frame_no == -1:
                    successful_count = processed_count  # Số ảnh OCR thành công
                    print(f"Hoàn thành xử lý OCR, đã xử lý tổng cộng {processed_count} hình ảnh")
                    print(f"Trong đó có {invalid_count[0]} hình ảnh không thể OCR")
                    print(f"📊 Thống kê: Tổng {total_processed} ảnh, OCR thành công {successful_count} ảnh, Lỗi {invalid_count[0]} ảnh")
                    print(f"📊 Chi tiết: {successful_count} ảnh thành công, {invalid_count[0]} ảnh lỗi, {total_processed - processed_count} ảnh bị bỏ qua")
                    return
                
                if frame is None:
                    print(f"Bỏ qua hình ảnh trống frame {frame_no}")
                    total_processed += 1  # Đếm ảnh trống
                    invalid_count[0] += 1
                    continue
                    
                data['i'] = frame_no
                processed_count += 1
                total_processed += 1
                
                extract_subtitles(data, text_recogniser, frame, raw_subtitle_file, sub_area, options, dt_box,
                                  rec_res, ocr_loss_debug_path, video_path, fps, invalid_count, total_ms=total_ms)
            except Exception as e:
                print(f"Lỗi xử lý OCR: {e}")
                total_processed += 1  # Đếm ảnh lỗi
                invalid_count[0] += 1
                break


def ocr_task_producer(ocr_queue, task_queue, progress_queue, video_path, raw_subtitle_path, processed_images=None):
    """
    生产者：负责生产用于OCR识别的数据，优先从RGBImages读取已处理的图像
    :param ocr_queue (current_frame_no当前帧帧号, frame 视频帧, dt_box检测框, rec_res识别结果)
    :param task_queue (total_frame_count总帧数, current_frame_no当前帧帧号, dt_box检测框, rec_res识别结果, subtitle_area字幕区域)
    :param progress_queue
    :param video_path
    :param raw_subtitle_path
    """
    cap = cv2.VideoCapture(video_path)
    tbar = None
    
    # 尝试从RGBImages目录读取已处理的图像
    # raw_subtitle_path 通常在 output/video_name/subtitle/raw.txt
    # RGBImages 在 output/video_name/RGBImages
    rgb_images_dir = os.path.join(os.path.dirname(os.path.dirname(raw_subtitle_path)), 'RGBImages')
    use_processed_images = os.path.exists(rgb_images_dir)
    
    print(f"Tìm kiếm thư mục RGBImages: {rgb_images_dir}")
    print(f"Thư mục tồn tại: {use_processed_images}")
    
    if use_processed_images:
        print(f"OCR sẽ sử dụng các hình ảnh đã xử lý từ: {rgb_images_dir}")
        # 获取所有已处理的图像文件
        processed_images = {}
        for filename in os.listdir(rgb_images_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                # 从文件名提取时间戳信息 - VSF格式: 0_00_00_033__...
                try:
                    time_part = filename.split('__')[0]
                    # 标准化时间格式: 0_00_00_033 -> 00_00_00_033
                    parts = time_part.split('_')
                    if len(parts) == 4:
                        h, m, s, ms = parts
                        time_key = f"{h.zfill(2)}_{m.zfill(2)}_{s.zfill(2)}_{ms.zfill(3)}"
                        processed_images[time_key] = os.path.join(rgb_images_dir, filename)
                except:
                    continue
        print(f"Tìm thấy {len(processed_images)} tập tin hình ảnh đã xử lý")
        if len(processed_images) > 0:
            print(f"Ví dụ tên tập tin: {list(processed_images.keys())[:3]}")
    else:
        print("OCR sẽ đọc trực tiếp từ các khung hình video")
    
    while True:
        try:
            # 从任务队列中提取任务信息
            total_frame_count, current_frame_no, dt_box, rec_res, total_ms, default_subtitle_area = task_queue.get(block=True)
            progress_queue.put(current_frame_no)
            if tbar is None:
                tbar = tqdm(total=round(total_frame_count), position=1)
            # current_frame 等于-1说明所有视频帧已经读完
            if current_frame_no == -1:
                # ocr识别队列加入结束标志
                ocr_queue.put((-1, None, None, None, None))
                # 更新进度条
                tbar.update(tbar.total - tbar.n)
                print(f"📤 Đã gửi tất cả ảnh đến OCR queue")
                break
            tbar.update(round(current_frame_no - tbar.n))
            
            frame = None
            
            # 优先使用已处理的图像
            if use_processed_images and total_ms is not None:
                # 从时间戳找到对应的已处理图像
                hours = int(total_ms // (60 * 60 * 1000))
                minutes = int((total_ms % (60 * 60 * 1000)) // (60 * 1000))
                seconds = int((total_ms % (60 * 1000)) // 1000)
                milliseconds = int(total_ms % 1000)
                time_key = f"{hours:02d}_{minutes:02d}_{seconds:02d}_{milliseconds:03d}"
                
                if time_key in processed_images:
                    frame = cv2.imread(processed_images[time_key])
                    if frame is not None:
                        print(f"Sử dụng hình ảnh đã xử lý: {time_key}")
                    else:
                        print(f"Không thể đọc hình ảnh đã xử lý: {time_key}")
                else:
                    print(f"Không tìm thấy hình ảnh đã xử lý tương ứng: {time_key}")
                    # 尝试找到最接近的图像 (按时间戳排序)
                    closest_key = None
                    min_diff = float('inf')
                    for key in processed_images.keys():
                        try:
                            key_parts = key.split('_')
                            if len(key_parts) == 4:
                                key_h, key_m, key_s, key_ms = map(int, key_parts)
                                key_total_ms = key_h * 3600000 + key_m * 60000 + key_s * 1000 + key_ms
                                diff = abs(total_ms - key_total_ms)
                                if diff < min_diff:
                                    min_diff = diff
                                    closest_key = key
                        except:
                            continue
                    
                    if closest_key and min_diff < 1000:  # 在1秒内
                        frame = cv2.imread(processed_images[closest_key])
                        if frame is not None:
                            print(f"Sử dụng hình ảnh gần nhất: {closest_key} (Chênh lệch: {min_diff}ms)")
            
            # 如果无法使用已处理图像，则从视频读取
            if frame is None:
                print(f"Đọc khung hình {current_frame_no} từ video")
                # 设置当前视频帧
                if total_ms is not None:
                    cap.set(cv2.CAP_PROP_POS_MSEC, total_ms)
                else:
                    # Sửa lỗi: current_frame_no bắt đầu từ 1, không cần trừ 1
                    cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_no - 1)
                # 读取视频帧
                ret, frame = cap.read()
                if not ret:
                    print(f"Không thể đọc khung hình {current_frame_no}")
                    # Thử đọc lại với cách khác
                    cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_no)
                    ret, frame = cap.read()
                    if not ret:
                        print(f"Vẫn không thể đọc khung hình {current_frame_no}")
                        continue
            
            # 根据默认字幕位置，则对视频帧进行裁剪，裁剪后处理
            if default_subtitle_area is not None:
                frame = frame_preprocess(default_subtitle_area, frame)
            ocr_queue.put((current_frame_no, frame, dt_box, rec_res, total_ms))
            # print(f"📤 Gửi ảnh {current_frame_no} đến OCR queue (total_ms: {total_ms})")
            
        except Exception as e:
            print(f"OCR生产者错误: {e}")
            break
    cap.release()


def subtitle_extract_handler(task_queue, progress_queue, video_path, raw_subtitle_path, sub_area, options, processed_images=None):
    """
    创建并开启一个视频帧提取线程与一个ocr识别线程
    :param task_queue 任务队列，(total_frame_count总帧数, current_frame_no当前帧, dt_box检测框, rec_res识别结果, subtitle_area字幕区域)
    :param progress_queue 进度队列
    :param video_path 视频路径
    :param raw_subtitle_path 原始字幕文件路径
    :param sub_area 字幕区域
    :param options 选项
    """
    # 删除缓存
    if os.path.exists(raw_subtitle_path):
        os.remove(raw_subtitle_path)
    # 创建一个OCR队列，大小建议值8-20
    from multiprocessing import Queue
    ocr_queue = Queue()
    # 创建一个OCR事件生产者线程
    ocr_event_producer_thread = Thread(target=ocr_task_producer,
                                       args=(ocr_queue, task_queue, progress_queue, video_path, raw_subtitle_path, processed_images,),
                                       daemon=True)
    # 创建一个OCR事件消费者提取线程
    ocr_event_consumer_thread = Thread(target=ocr_task_consumer,
                                       args=(ocr_queue, raw_subtitle_path, sub_area, video_path, options, processed_images,),
                                       daemon=True)
    # 开启消费者线程
    ocr_event_producer_thread.start()
    # 开启生产者线程
    ocr_event_consumer_thread.start()
    # join方法让主线程任务结束之后，进入阻塞状态，一直等待其他的子线程执行结束之后，主线程再终止
    ocr_event_producer_thread.join()
    ocr_event_consumer_thread.join()


def async_start(video_path, raw_subtitle_path, sub_area, options, task_queue=None, progress_queue=None,
                processed_images=None, use_process=True):
    """
    开始进程处理异步任务
    options.REC_CHAR_TYPE
    options.DROP_SCORE
    options.SUB_AREA_DEVIATION_RATE
    options.DEBUG_OCR_LOSS
    """
    assert 'REC_CHAR_TYPE' in options, "options缺少参数：REC_CHAR_TYPE"
    assert 'DROP_SCORE' in options, "options缺少参数: DROP_SCORE'"
    assert 'SUB_AREA_DEVIATION_RATE' in options, "options缺少参数: SUB_AREA_DEVIATION_RATE"
    assert 'DEBUG_OCR_LOSS' in options, "options缺少参数: DEBUG_OCR_LOSS"
    # 创建一个任务队列 (如果未提供则创建新的)
    # 任务格式为：(total_frame_count总帧数, current_frame_no当前帧, dt_box检测框, rec_res识别结果, subtitle_area字幕区域)
    if task_queue is None:
        from multiprocessing import Queue
        task_queue = Queue()
    if progress_queue is None:
        from multiprocessing import Queue
        progress_queue = Queue()
    worker_args = (task_queue, progress_queue, video_path, raw_subtitle_path, sub_area,
                   SimpleNamespace(**options), processed_images,)

    if use_process:
        # 新建一个进程
        worker = Process(target=subtitle_extract_handler, args=worker_args)
        # 启动进程
        worker.start()
    else:
        # 在 frozen 模式下优先线程，避免 multiprocessing 在打包环境下崩溃。
        worker = Thread(target=subtitle_extract_handler, args=worker_args, daemon=True)
        worker.start()

    return worker, task_queue, progress_queue


def frame_preprocess(subtitle_area, frame):
    """
    将视频帧进行裁剪
    """
    # 对于分辨率大于1920*1080的视频，将其视频帧进行等比缩放至1280*720进行识别
    # paddlepaddle会将图像压缩为640*640
    # if self.frame_width > 1280:
    #     scale_rate = round(float(1280 / self.frame_width), 2)
    #     frames = cv2.resize(frames, None, fx=scale_rate, fy=scale_rate, interpolation=cv2.INTER_AREA)
    # 如果字幕出现的区域在下部分
    if subtitle_area == SubtitleArea.LOWER_PART:
        cropped = int(frame.shape[0] // 2)
        # 将视频帧切割为下半部分
        frame = frame[cropped:]
    # 如果字幕出现的区域在上半部分
    elif subtitle_area == SubtitleArea.UPPER_PART:
        cropped = int(frame.shape[0] // 2)
        # 将视频帧切割为下半部分
        frame = frame[:cropped]
    return frame


if __name__ == "__main__":
    pass
