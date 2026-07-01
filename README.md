<p align="center">
  <img src="custom_components/evn_vietnam/brand/icon.png" alt="EVN Vietnam" width="140">
</p>

<h1 align="center">EVN Vietnam cho Home Assistant</h1>

<p align="center">
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge" alt="HACS Custom"></a>
  <a href="https://github.com/MinhPC/evn_vietnam/releases"><img src="https://img.shields.io/badge/version-1.0.0-blue.svg?style=for-the-badge" alt="Version"></a>
  <a href="https://github.com/MinhPC"><img src="https://img.shields.io/badge/maintainer-%40MinhPC-brightgreen.svg?style=for-the-badge" alt="Maintainer"></a>
</p>

Custom integration giúp theo dõi **điện năng tiêu thụ**, **chỉ số công tơ**, **tiền điện (tạm tính)** và **tình trạng hóa đơn** từ [EVN](https://www.evn.com.vn) trực tiếp trên [Home Assistant](https://www.home-assistant.io). Hỗ trợ cả **5 tổng công ty điện lực** trên toàn quốc, tự động nhận diện khu vực dựa trên mã khách hàng.

> Dữ liệu được lấy qua các API công khai của EVN bằng `aiohttp`, cập nhật định kỳ và hiển thị dưới dạng các sensor của Home Assistant.

---

## Mục lục

- [Tính năng](#tính-năng)
- [Khu vực hỗ trợ](#khu-vực-hỗ-trợ)
- [Yêu cầu](#yêu-cầu)
- [Cài đặt](#cài-đặt)
- [Thiết lập](#thiết-lập)
- [Danh sách sensor](#danh-sách-sensor)
- [Cách tính tiền điện](#cách-tính-tiền-điện)
- [Ví dụ Automation](#ví-dụ-automation)
- [Hạn chế đã biết](#hạn-chế-đã-biết)
- [Đóng góp](#đóng-góp)

---

## Tính năng

- 📊 Theo dõi **sản lượng điện** theo **ngày** (hôm nay / hôm qua) và **theo tháng** (tạm chốt).
- 💰 Ước tính **tiền điện** theo ngày và theo tháng dựa trên biểu giá bậc thang sinh hoạt.
- 🔢 Đọc **chỉ số công tơ** đầu kỳ và chỉ số tạm chốt mới nhất.
- 🧾 Kiểm tra **tình trạng hóa đơn** và **số tiền còn nợ** (nếu có).
- ⚡ Xem **lịch cắt điện** (hiện hỗ trợ khu vực miền Nam – EVNSPC).
- 🏢 Hỗ trợ **nhiều mã khách hàng** cùng lúc trên một máy chủ Home Assistant.
- 🖱️ Cài đặt và cấu hình hoàn toàn qua **giao diện UI** (config flow), không cần chỉnh sửa YAML.
- 🌏 **Tự động nhận diện** tổng công ty EVN từ mã khách hàng.

## Khu vực hỗ trợ

| Tổng công ty | Khu vực | Mã KH bắt đầu bằng | Cần ngày chốt kỳ | Ghi chú |
|:---|:---|:---:|:---:|:---|
| **EVNHANOI** | Thủ đô Hà Nội | `PD` | ✅ | |
| **EVNHCMC** | TP. Hồ Chí Minh | `PE` | ✅ | |
| **EVNNPC** | Miền Bắc | `PA` `PH` `PM` `PN` | ✅ | |
| **EVNCPC** | Miền Trung | `PQ` `PC` `PP` | ❌ | Tự xác định kỳ theo dữ liệu EVN |
| **EVNSPC** | Miền Nam | `PB` `PK` | ✅ | Có thêm sensor lịch cắt điện |

## Yêu cầu

1. **Home Assistant** phiên bản **2024.8.0** trở lên.
2. **Công tơ điện tử đo xa, ghi chỉ số theo ngày.** Nếu bạn xem được *sản lượng theo ngày* trên website/app chính thức của EVN thì công tơ của bạn tương thích.
3. **Tài khoản EVN** hợp lệ ở khu vực tương ứng, gồm:
   - Tên đăng nhập (thường là mã khách hàng hoặc số điện thoại)
   - Mật khẩu
4. **Mã khách hàng** hợp lệ: dài **11–13 ký tự**, bắt đầu bằng chữ **`P`** (ví dụ: `PE06000012345`).

> Nếu chưa có tài khoản đăng nhập, hãy liên hệ Trung tâm Chăm sóc Khách hàng (TTCSKH) của tổng công ty điện lực tại khu vực của bạn để được cấp.

## Cài đặt

### Cách 1 — Qua HACS (khuyến nghị)

1. Mở **HACS → Integrations**.
2. Bấm menu (⋮ góc trên bên phải) → **Custom repositories**.
3. Thêm repository: `https://github.com/MinhPC/evn_vietnam` — Category: **Integration**.
4. Tìm **EVN Vietnam** trong danh sách, bấm **Download**.
5. **Khởi động lại** Home Assistant.

### Cách 2 — Thủ công

1. Tải mã nguồn mới nhất từ [GitHub](https://github.com/MinhPC/evn_vietnam).
2. Sao chép thư mục `custom_components/evn_vietnam` vào thư mục `custom_components` của Home Assistant (nơi chứa `configuration.yaml`).
3. Cấu trúc thư mục sau khi cài đặt:

   ```
   <thư mục cấu hình HA>/
   ├── configuration.yaml
   └── custom_components/
       └── evn_vietnam/
           ├── __init__.py
           ├── sensor.py
           ├── evn_core.py
           └── ...
   ```

4. **Khởi động lại** Home Assistant.

## Thiết lập

Vào **Settings → Devices & Services → Add Integration**, tìm **EVN Vietnam**, sau đó làm theo các bước:

1. **Nhập mã khách hàng** (11–13 ký tự, bắt đầu bằng `P`).
2. **Xác nhận khu vực EVN** được tự động nhận diện (tổng công ty, địa điểm, chi nhánh).
3. **Nhập tài khoản EVN** (username, password). Với các khu vực cần chốt kỳ, chọn thêm **Ngày bắt đầu hóa đơn** (1–28, mặc định `24`) — đây là ngày đầu tiên trong kỳ hóa đơn hàng tháng, xem trên hóa đơn các kỳ trước để biết chính xác.
4. Hoàn tất — thiết bị và các sensor sẽ xuất hiện trong **Devices**.

> Có thể lặp lại quy trình trên để thêm nhiều mã khách hàng khác nhau.

## Danh sách sensor

Mỗi mã khách hàng tạo ra một thiết bị với các sensor sau (entity ID có dạng `sensor.<mã_khách_hàng>_<key>`):

| Sensor | `key` | Đơn vị | Mô tả |
|:---|:---|:---:|:---|
| Sản lượng (hôm nay) | `econ_daily_new` | kWh | Sản lượng của ngày tạm chốt mới nhất |
| Tiền điện (hôm nay) | `ecost_daily_new` | VNĐ | Tiền điện tạm tính của ngày tạm chốt mới nhất |
| Sản lượng (hôm trước) | `econ_daily_old` | kWh | Sản lượng của ngày liền trước |
| Tiền điện (hôm trước) | `ecost_daily_old` | VNĐ | Tiền điện tạm tính của ngày liền trước |
| Sản lượng tháng này | `econ_monthly_new` | kWh | Tổng sản lượng từ đầu kỳ đến ngày tạm chốt |
| Tiền điện tháng này | `ecost_monthly_new` | VNĐ | Tiền điện tạm tính của tháng hiện tại |
| Chỉ số tạm chốt | `econ_total_new` | kWh | Chỉ số công tơ mới nhất (tăng dần) |
| Chỉ số đầu kì | `econ_total_old` | kWh | Chỉ số công tơ đầu kỳ hóa đơn |
| Ngày tạm chốt | `to_date` | — | Ngày của dữ liệu mới nhất |
| Ngày đầu kì | `from_date` | — | Ngày bắt đầu kỳ hóa đơn |
| Lần cập nhật cuối | `latest_update` | timestamp | Thời điểm integration cập nhật dữ liệu gần nhất |
| Hóa đơn cũ | `payment_needed` | — | Tình trạng hóa đơn (đã / chưa thanh toán) |
| Tiền nợ | `m_payment_needed` | VNĐ | Số tiền còn nợ (nếu có) |
| Lịch cắt điện | `loadshedding` | — | Lịch ngừng/giảm cung cấp điện (EVNSPC) |

Các sensor **Sản lượng / Tiền điện** theo ngày có tên hiển thị **động**: tự đổi thành *“hôm nay”, “hôm qua”, “hôm kia”* hoặc *“ngày dd/mm”* tùy thời điểm của dữ liệu.

## Cách tính tiền điện

Các sensor tiền điện được **tính thủ công** từ sản lượng theo **biểu giá bán lẻ điện sinh hoạt** (6 bậc) cộng **VAT 8%**:

| Bậc | Mức tiêu thụ | Đơn giá (đ/kWh) |
|:---:|:---|:---:|
| 1 | 0 – 50 kWh | 1.984 |
| 2 | 51 – 100 kWh | 2.050 |
| 3 | 101 – 200 kWh | 2.380 |
| 4 | 201 – 300 kWh | 2.998 |
| 5 | 301 – 400 kWh | 3.350 |
| 6 | > 400 kWh | 3.460 |

> ⚠️ Đây chỉ là **con số tham khảo**, không lấy trực tiếp từ EVN. Sản lượng ngày lẻ được áp giá bậc thang nên **sai số có thể lớn**. Biểu giá được khai báo trong [`const.py`](custom_components/evn_vietnam/const.py) (`VIETNAM_ECOST_STAGES`, `VIETNAM_ECOST_VAT`) — bạn có thể chỉnh khi EVN cập nhật giá. Xem biểu giá chính thức tại [evn.com.vn](https://www.evn.com.vn/c3/evn-va-khach-hang/Bieu-gia-ban-le-dien-9-79.aspx).

## Ví dụ Automation

Gửi thông báo điện năng tiêu thụ mỗi sáng. Thay `<device>` bằng phần định danh mã khách hàng của bạn (ví dụ `pe06000012345`):

```yaml
alias: Thông báo điện tiêu thụ mỗi ngày
mode: single

trigger:
  - platform: time
    at: "08:00:00"

# Chỉ báo khi đã có dữ liệu của ngày hôm qua
condition:
  - condition: template
    value_template: >-
      {{ states('sensor.<device>_to_date')
         == (now() - timedelta(days=1)).strftime('%d/%m/%Y') }}

action:
  - service: notify.notify
    data:
      title: "⚡ Điện tiêu thụ"
      message: >-
        Ngày {{ states('sensor.<device>_to_date') }}:
        {{ states('sensor.<device>_econ_daily_new') }} kWh
        (~{{ states('sensor.<device>_ecost_daily_new') }} VNĐ)
```

## Hạn chế đã biết

- Dữ liệu **không cập nhật tức thời**: integration làm mới theo chu kỳ **mỗi 3 giờ**. EVN cũng thường chỉ có dữ liệu của ngày hôm trước.
- Chỉ hỗ trợ **hộ sinh hoạt** dùng công tơ điện tử đo xa ghi theo ngày; chưa hỗ trợ điện 3 pha / mục đích sản xuất, kinh doanh.
- Sensor tiền điện chỉ **mang tính tham khảo** (xem [Cách tính tiền điện](#cách-tính-tiền-điện)).
- Sensor **lịch cắt điện** hiện chỉ khả dụng ở khu vực miền Nam (EVNSPC).
- Chưa tích hợp hoàn chỉnh vào bảng **Energy** của Home Assistant.

## Đóng góp

Mọi issue và pull request đều được hoan nghênh tại [MinhPC/evn_vietnam](https://github.com/MinhPC/evn_vietnam).

Nếu khu vực hoặc chi nhánh EVN của bạn chưa được hỗ trợ, hãy tạo issue kèm thông tin mã khách hàng (đã che bớt) để được hỗ trợ thêm.
