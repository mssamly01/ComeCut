# Roadmap ComeCut Local Theo Hướng CapCut

Mục tiêu sản phẩm: ComeCut là trình chỉnh sửa video chạy local, độc lập, có workflow và cảm giác sử dụng tương tự CapCut, nhưng không phụ thuộc server, cloud render, hay API CapCut/VectCutAPI.

## Nguyên Tắc Kiến Trúc

- Local-first: mọi tính năng cốt lõi phải chạy offline trên máy người dùng.
- FFmpeg là render engine chính cho export video.
- PySide6 là UI editor chính.
- Project model riêng của ComeCut là nguồn dữ liệu chuẩn.
- CapCut-compatible import/export chỉ là bridge phụ, không phải lõi ứng dụng.
- Không chạy HTTP server trong app desktop.
- Không đưa secret, OSS config, cloud endpoint vào workflow mặc định.
- Mọi thao tác UI làm thay đổi project phải đi qua history/undo transaction.
- Thao tác drag liên tục như trim, move, keyframe, crop, transform phải gom thành 1 undo step.

## Phase 1 - Timeline/Preview Reliability

Mục tiêu: playback/editing có cảm giác chắc tay, ít giật, đúng sync.

Việc cần làm:

- Ổn định timeline audio preview: video, audio track, playhead sync, seek/scrub.
- Hoàn thiện waveform: volume, fade in/out, muted/hidden state, speed-aware display.
- Thêm trim edge handles rõ ràng hơn cho clip.
- Thêm ripple trim/ripple delete tùy chọn.
- Thêm snap theo clip edges, playhead, marker, subtitle boundaries.
- Cải thiện auto-advance giữa các clip không liên tục.
- Proxy preview cho video dài/nặng, ưu tiên tạo proxy nền.
- Thêm QA checklist cho project thật có video, audio, subtitle, text overlay.
- Thêm regression tests cho preview/timeline helper.

Acceptance:

- Play 30 giây với 1 video + 2 audio tracks không mất sync rõ ràng.
- Seek/scrub liên tục không phát sót source cũ.
- Fade/volume/speed thay đổi khi đang play được nghe/nhìn cập nhật nhanh.
- Timeline helper test pass sau mỗi thay đổi liên quan preview/playhead.

## Phase 2 - Inspector + Canvas Controls

Mục tiêu: chỉnh clip nhanh trong panel phải và thao tác trực tiếp trên preview theo kiểu CapCut.

Việc cần làm:

- Video transform: position, scale, scale X/Y, rotate, opacity.
- Preview canvas transform handles: move, resize, rotate selected visual clip.
- Crop UI trực quan trên preview, có crop handles.
- Center guides và safe-area guides.
- Flip horizontal/vertical.
- Speed controls: normal speed, duration lock, possible speed curve sau.
- Audio controls: volume dB, fade in/out, speed, denoise, normalize, voice preset.
- Reset button cho từng nhóm setting.
- Keyframe button cho các property quan trọng.
- Undo transaction grouping cho drag/slider/transform liên tục.

Acceptance:

- Chọn 1 clip là inspector cập nhật đúng loại clip.
- Kéo control thay đổi preview ngay.
- Kéo canvas handle cập nhật clip transform và gom thành 1 undo step.
- Undo/redo giữ đúng state inspector, preview và timeline.

## Phase 3 - Keyframe Foundation

Mục tiêu: có nền keyframe dùng chung cho motion, audio, opacity, template và render local.

Thứ tự triển khai:

1. Model hóa keyframes trong project model cho các property cần thiết.
2. Thêm evaluator nội suy keyframe theo timeline time.
3. Thêm UI diamond tối thiểu trên timeline/inspector.
4. Ưu tiên volume và opacity keyframes trước.
5. Thêm transform keyframes: x, y, scale, scale X/Y, rotation.
6. Preview nội suy keyframe theo playhead.
7. FFmpeg render keyframe volume/opacity/transform.
8. Motion presets cơ bản: zoom in, zoom out, slide left/right, fade in/out.
9. Copy/paste keyframes giữa clip.

Acceptance:

- Thêm 2 keyframes volume/opacity và preview thay đổi liên tục.
- Thêm 2 keyframes scale/position và preview thay đổi liên tục.
- Export MP4 local khớp gần đúng preview.

## Phase 3.5 - Preset Foundation Tối Thiểu

Mục tiêu: có nền preset local sớm để các tính năng mới nhanh có cảm giác giống CapCut.

Việc cần làm:

- JSON preset loader local.
- Apply preset to selected clip.
- Text style preset cơ bản.
- Effect/filter preset cơ bản.
- Motion preset cơ bản dựa trên keyframes.
- Export preset cơ bản cho social formats.

Acceptance:

- Preset local load được không cần internet.
- Áp preset cho selected clip không làm hỏng undo/redo.

## Phase 4 - Text Và Subtitle Mạnh

Mục tiêu: text/subtitle là điểm mạnh như CapCut, dùng tốt cho workflow content ngắn.

Việc cần làm:

- Text clip style: font, size, color, stroke, shadow, background.
- Text position/scale/rotation trên preview.
- Text preset JSON.
- Subtitle style preset.
- Subtitle list + timeline sync tốt hơn.
- Batch split/merge subtitle.
- Auto style presets cho subtitle.
- Bilingual subtitle workflow: main/second, display mode, export SRT/ASS.
- OCR/ASR workflow local hoặc optional provider qua plugin.

Acceptance:

- Import SRT, sửa text trong list, timeline/preview sync đúng.
- Export SRT/ASS rõ ràng.
- Export video burn-in subtitle đúng style cơ bản.

## Phase 5 - Audio Workflow

Mục tiêu: audio edit đủ dùng cho short-form video và project nhiều track.

Thứ tự triển khai:

1. Audio volume keyframes.
2. Track mixer: mute, solo, volume, pan, audio role.
3. Master limiter sau mix để tránh clipping.
4. Peak meter/clipping warning cơ bản.
5. Denoise/normalize UI.
6. Voice preset cho audio-only clip.
7. Auto ducking tạo volume keyframes cho music khi dialogue/voiceover phát.
8. Beat markers local + snap.

Acceptance:

- Track mixer điều khiển được audio toàn track.
- Master limiter giảm rủi ro clipping rõ ràng khi nhiều audio track cùng phát.
- Nhạc nền tự động giảm khi voiceover phát và user chỉnh lại được qua volume keyframes.
- Beat markers snap được clip/video cuts.
- Export audio mix không clip/distort rõ ràng.

## Phase 6 - Effects, Filters, Transitions

Mục tiêu: có bộ effect cơ bản, ổn định, render local.

Việc cần làm:

- Filter presets: brightness, contrast, saturation, grayscale, blur.
- Effect stack order rõ ràng.
- Enable/disable từng effect.
- Reset effect group.
- Transition UI giữa 2 clips cùng track.
- Transition render: fade, dissolve, wipe, slide.
- Preview approximation cho effect phổ biến.

Acceptance:

- Kéo transition giữa 2 clip và export đúng.
- Bật/tắt filter trong inspector, preview cập nhật ngay.
- Effect stack không làm hỏng undo/redo.

## Phase 7 - Local Templates/Presets

Mục tiêu: tăng tốc workflow tạo video lặp lại.

Việc cần làm:

- Local template format cho text style, subtitle style, motion preset, effect preset, export preset.
- Template browser trong UI.
- Save current clip style as preset.
- Apply preset to selected clips.
- Project template: canvas, tracks, default subtitle style.
- Template storage dưới thư mục cấu hình local của ComeCut.

Acceptance:

- User tạo style subtitle một lần, áp dụng lại được trong project khác.
- Template local không cần đăng nhập, server, hay internet.

## Phase 8 - Render, Export Và Performance

Mục tiêu: export local đáng tin cậy và app vẫn mượt với project dài.

Việc cần làm:

- Export dialog rõ ràng: resolution, fps, bitrate, format, audio bitrate.
- Export preset social formats.
- Queue export local.
- Progress + cancel.
- Hardware encoder optional nếu máy hỗ trợ.
- Proxy generation workflow.
- Cache cleanup.
- Export still frame.
- Export audio only.
- Export subtitle SRT/ASS.

Acceptance:

- Export MP4 dài vẫn có progress/cancel.
- Lỗi FFmpeg hiện message dễ hiểu.
- Cache/proxy không phình vô hạn mà không có cách dọn.

## Optional Later - CapCut-Compatible Bridge

Mục tiêu: bridge phụ cho user muốn mở tiếp trong CapCut, không nằm trong MVP và không làm lõi ứng dụng.

Việc có thể làm sau:

- Đổi wording UI thành "Export CapCut-compatible Draft (Experimental)".
- Xuất draft folder đầy đủ hơn, không chỉ 1 file nếu có thể.
- Tùy chọn copy media vào draft assets.
- Import CapCut draft tiếp tục cải thiện mapping.
- Ghi warnings khi effect/keyframe không map được.
- Không chạy VectCutAPI server.
- Không dùng cloud endpoint.

Acceptance:

- Project có video + audio + text export ra draft mở được trong CapCut/Jianying ở mức cơ bản.
- Nếu không map được effect, ComeCut export tiếp và báo warning.

## Ưu Tiên Gần Nhất

Thứ tự nên làm tiếp:

1. Manual QA timeline/audio preview với project thật.
2. Trim/ripple/snap cơ bản trên timeline.
3. Keyframe foundation.
4. Track mixer + master limiter/audio meter.
5. Audio inspector enhance.
6. Auto ducking dựa trên volume keyframes.
7. Beat markers local + snap.
8. Preset system local.
9. CapCut-compatible bridge chỉ để Optional/Later.

## Những Việc Không Nên Làm

- Không thay FFmpeg render bằng CapCut/VectCutAPI.
- Không đưa Flask server vào app desktop.
- Không bắt người dùng đăng nhập CapCut.
- Không gọi cloud render mặc định.
- Không quảng bá là official CapCut API.
- Không copy toàn bộ repo VectCutAPI nếu chỉ cần schema/reference.
