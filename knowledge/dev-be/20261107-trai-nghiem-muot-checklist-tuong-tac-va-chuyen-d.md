---
title: Trải nghiệm mượt: checklist tương tác và chuyển động
kind: checklist
priority: cao
status: active
source: trai_nghiem.xlsx, CTO 07/11/2026
by: cto
created: 2026-11-07T11:35:37
updated: 2026-11-07T11:35:37
---
Áp cho mọi block, snippet, trang của theme. Nguồn: file trai_nghiem.xlsx của CTO (07/11/2026). Giao diện theo Figma, dữ liệu luôn lấy động; chuyển động là lớp thêm, không đổi bố cục tĩnh của Figma.

Mỗi tương tác phải làm được một trong 4 việc: công nhận hành động, hướng dẫn người dùng, giao tiếp trạng thái, tạo cảm xúc. Không làm được việc nào thì không thêm hiệu ứng.

Token: chỉ dùng --motion-fast (150ms), --motion-base (250ms), --motion-slow (500ms), --ease-out, --ease-in-out. Không viết thời gian rời trong CSS.

Checklist theo thành phần:
- Cuộn: anchor cuộn mượt; nội dung trượt và hiện dần một lần khi vào khung nhìn. Danh sách dài ngoài trang chủ: cân nhắc tải thêm không giật.
- Nút: đủ 6 trạng thái default, hover, active, loading, disabled, focus-visible. Đổi trạng thái có transition, hover có phản hồi, active nhún nhẹ, loading có spinner màu thương hiệu.
- Form: focus đổi viền có transition; placeholder gợi ý định dạng; validation có viền và thông báo cụ thể ("Email không hợp lệ"); kiểm tra ngay khi nhập khi làm được.
- Product card: hover phóng ảnh nhẹ; có ảnh thứ hai thì hiện khi hover; swatch đổi ảnh, có dấu tick đã chọn.
- Điều hướng: menu con mở bằng fade và trượt, chữ menu con luôn đọc được khi hover; đánh dấu trang hiện tại; thêm giỏ thì số giỏ đổi, icon nhún, giỏ trượt ra.
- Carousel, tab, accordion: có chỉ báo active; icon accordion xoay mượt; nội dung trượt hoặc mờ hiện ra, không đổi đột ngột.
- Popup, drawer, modal: hiện và ẩn đều có transition; overlay fade; thông báo khi có sự kiện xảy ra.
- Tải dữ liệu: tải có bố cục biết trước dùng skeleton; tác vụ nền dùng spinner riêng của thương hiệu; biết tiến độ thì dùng progress bar.

Ràng buộc kỹ thuật:
- Chỉ animate transform và opacity (chiều cao accordion dùng ::details-content). Không gây layout shift; Lighthouse giữ performance ≥ 96 desktop, ≥ 90 mobile, accessibility ≥ 98.
- Mọi chuyển động nằm trong prefers-reduced-motion: no-preference. Không JS vẫn dùng được, trạng thái cuối luôn đọc được.
- CSS trước. JS chỉ khi CSS không làm được và là việc Dev BE; không thêm thư viện animation.
- Focus nhìn thấy được, vùng chạm 44px, tương phản AA (ngoại lệ đã duyệt trong tests/e2e/support/figma-exceptions.json).
