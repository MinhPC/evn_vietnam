# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này.

## Tổng quan

Home Assistant **custom integration** (`domain: evn_vietnam`) đọc dữ liệu điện năng từ API của 5 tổng công ty điện lực Việt Nam (EVNHANOI, EVNHCMC, EVNNPC, EVNCPC, EVNSPC) và hiển thị thành sensor. Toàn bộ code nằm trong [`custom_components/evn_vietnam/`](custom_components/evn_vietnam/). README.md dành cho người dùng cuối; file này dành cho việc phát triển.

- Ngôn ngữ: Python, async (`aiohttp` qua HA client session).
- `iot_class`: `cloud_polling`, chu kỳ cập nhật **3 giờ** (`DEFAULT_SCAN_INTERVAL` trong `const.py`).
- Không có test tự động, không có LICENSE, không dùng `requirements.txt` (dependencies khai báo ở `manifest.json`).

## Cấu trúc file

| File | Vai trò |
|:---|:---|
| `__init__.py` | Vòng đời config entry: setup/unload/reload, forward sang platform `sensor`. |
| `config_flow.py` | Luồng cấu hình UI nhiều bước: `customer_id` → `evn_info` → `fulfill_data`. |
| `evn_core.py` | **Trái tim của integration.** Class `EVNAPI` với login/request per-area, chuẩn hoá dữ liệu, tính tiền điện. |
| `sensor.py` | `EVNDevice` (wrap coordinator) + `EVNSensor` (CoordinatorEntity). |
| `types.py` | Dataclass `Area`, hằng `EVN_NAME`, danh sách `VIETNAM_EVN_AREA` (URL + pattern mã KH), và `EVN_SENSORS` (mô tả 14 sensor). |
| `const.py` | Hằng số: key config/status, ID sensor, biểu giá điện, VAT, scan interval. |
| `evn_branches.json` | Map mã đơn vị → tên chi nhánh (load runtime). |
| `strings.json` / `translations/{en,vi}.json` | Text config flow. |

## Kiến trúc & luồng dữ liệu

1. **Config flow** (`config_flow.py`): người dùng nhập mã KH → `evn_core.get_evn_info_sync()` khớp `pattern` trong `VIETNAM_EVN_AREA` để xác định khu vực → nhập tài khoản → verify bằng `login()` + `request_update()`.
2. **Runtime** (`sensor.py`): mỗi entry tạo `EVNDevice` → `DataUpdateCoordinator` gọi `EVNDevice.update()` mỗi 3 giờ → `EVNAPI.request_update()`.
3. **`EVNAPI.request_update()`** (`evn_core.py`) dispatch theo `evn_area["name"]` tới `request_update_evn<area>()`. Mỗi area có endpoint và định dạng response riêng, nhưng đều trả về dict với các ID chung (`ID_ECON_*`, `ID_PAYMENT_NEEDED`, ...).
4. Kết quả đi qua **`formatted_result()`** → bọc mỗi giá trị thành `{"value": ..., "info": ...}` (info dùng cho dynamic name/icon).
5. `EVNSensor.native_value` đọc `value_fn(data)` từ mô tả trong `EVN_SENSORS`.

### Quy ước per-area (quan trọng)

Mỗi tổng công ty có endpoint, header, payload và cấu trúc JSON **khác nhau**. Khi sửa một area, KHÔNG giả định các area khác giống nhau. Đặc thù đã biết:

- **EVNCPC**: `date_needed=False` — không cần ngày chốt kỳ; dùng endpoint riêng trả sẵn today/yesterday/this-month.
- **EVNSPC**: có `evn_loadshedding_url` (lịch cắt điện); login cần `customer_id` làm `strDeviceID`; dùng `fetch_with_retries()`.
- **EVNHANOI/HCMC/NPC/CPC**: cơ chế token/session khác nhau (Bearer token, cookie `evn_session`, Basic auth...).
- **EVNHANOI**: có retry `last_index` "001" → "1" khi mã điểm đo lỗi 400.

### Thêm một area / chi nhánh mới

1. Thêm `Area(...)` vào `VIETNAM_EVN_AREA` trong `types.py` (name, location, URL, `pattern` mã KH, cờ `date_needed`).
2. Nếu là tổng công ty mới: thêm hằng vào `EVN_NAME`, viết `login_evnX()` + `request_update_evnX()` trong `EVNAPI`, và thêm nhánh dispatch trong `login()` và `request_update()`.
3. Trả về dict dùng các ID chung trong `const.py` để `formatted_result()` xử lý được.

## Quy ước code

- **Async-first**: mọi I/O mạng qua `self._session` (aiohttp). Việc blocking (đọc file, tạo SSL context) phải chạy qua `hass.async_add_executor_job(...)` — xem `read_evn_branches_file`, `create_ssl_context`, `get_evn_info_sync`.
- **Status codes** là string trong `const.py` (`CONF_SUCCESS = "success"`, `CONF_ERR_*`), không phải enum. Hàm trả `(status, data)` hoặc dict có key `"status"`.
- **Tiền điện** tính thủ công trong `calc_ecost()` theo biểu giá bậc thang `VIETNAM_ECOST_STAGES` + `VIETNAM_ECOST_VAT` (const.py). Cập nhật giá = sửa 2 hằng này.
- **Dynamic name/icon**: sensor có `dynamic_name=True` đổi tên hiển thị theo `info` (hôm nay/hôm qua/ngày dd/mm); `dynamic_icon=True` đổi icon theo trạng thái.
- **Đổi version**: sửa ĐỒNG THỜI `manifest.json` (`"version"`) và `const.py` (`CONF_DEVICE_SW_VERSION`). Hiện tại: **1.0.0**.
- Text hiển thị chủ yếu bằng **tiếng Việt** — giữ nguyên phong cách khi thêm string; đồng bộ cả `translations/en.json` và `vi.json`.

## Kiểm tra trước khi commit

Không có test suite. Tối thiểu:

```bash
# Compile toàn bộ Python
python -m py_compile custom_components/evn_vietnam/*.py

# Validate JSON (manifest, hacs, translations, branches)
python -c "import json,glob;[json.load(open(f,encoding='utf-8')) for f in glob.glob('custom_components/evn_vietnam/**/*.json',recursive=True)+['hacs.json']];print('OK')"
```

CI trên GitHub (nếu bật lại thư mục `.github/`): HACS validation + hassfest. Xác thực thật cần chạy trong một instance Home Assistant với tài khoản EVN hợp lệ.

## Cạm bẫy đã biết

- Nhánh reauth trong `sensor.py::EVNDevice.update()` và các chỗ raise `ConfigEntryNotReady` từng có bug về import/tham số — nếu sửa, kiểm tra kỹ signature của `login()` (cần `customer_id`) và `request_update()` (cần `username, password, customer_id, monthly_start`).
- Tránh `datetime.strftime("%-d"/"%-m")` (chỉ chạy trên Linux); dùng `.day`/`.month`.
- `__pycache__/` và `.github/` (nếu người dùng đã xoá) không nên vô tình commit — kiểm tra `.gitignore`.
- File này giả định mọi thay đổi giữ nguyên bản chất "custom component đọc-only từ API EVN"; không thêm ghi/điều khiển thiết bị.
