"""Setup and manage the EVN API."""

import asyncio
import base64
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import ssl
import time
from typing import Any

from dateutil import parser

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)

from .const import (
    CONF_EMPTY,
    CONF_ERR_CANNOT_CONNECT,
    CONF_ERR_INVALID_AUTH,
    CONF_ERR_INVALID_ID,
    CONF_ERR_NO_MONITOR,
    CONF_ERR_NOT_SUPPORTED,
    CONF_ERR_UNKNOWN,
    CONF_SUCCESS,
    ID_ECON_DAILY_NEW,
    ID_ECON_DAILY_OLD,
    ID_ECON_MONTHLY_NEW,
    ID_ECON_TOTAL_NEW,
    ID_ECON_TOTAL_OLD,
    ID_ECOST_DAILY_NEW,
    ID_ECOST_DAILY_OLD,
    ID_ECOST_MONTHLY_NEW,
    ID_FROM_DATE,
    ID_LATEST_UPDATE,
    ID_M_PAYMENT_NEEDED,
    ID_PAYMENT_NEEDED,
    ID_LOADSHEDDING,
    ID_TO_DATE,
    STATUS_N_PAYMENT_NEEDED,
    STATUS_PAYMENT_NEEDED,
    STATUS_LOADSHEDDING,
    VIETNAM_ECOST_STAGES,
    VIETNAM_ECOST_VAT,
)
from .types import EVN_NAME, VIETNAM_EVN_AREA, Area

_LOGGER = logging.getLogger(__name__)

EVN_BRANCHES_FILE = os.path.join(os.path.dirname(__file__), "evn_branches.json")

UA_BROWSER = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36"
)
UA_NPC = "NPCApp/1 CFNetwork/1240.0.4 Darwin/20.6.0"
UA_SPC = "evnapp/59 CFNetwork/1240.0.4 Darwin/20.6.0"

# Tạo SSL context là thao tác blocking & tốn kém -> chỉ tạo một lần rồi cache.
_SSL_CONTEXTS: dict[str, ssl.SSLContext] = {}

# Cache nội dung evn_branches.json (dùng chung cho config flow & sensor).
_BRANCHES_CACHE: dict[str, str] | None = None


def create_ssl_context():
    """Create SSL context with cipher settings"""
    context = ssl.create_default_context()
    context.set_ciphers("ALL:@SECLEVEL=1")
    return context


async def async_get_ssl_context(hass: HomeAssistant, legacy: bool = False):
    """Return a cached SSL context (legacy=True: cho phép cipher cũ)."""
    key = "legacy" if legacy else "default"
    if key not in _SSL_CONTEXTS:
        _SSL_CONTEXTS[key] = await hass.async_add_executor_job(
            create_ssl_context if legacy else ssl.create_default_context
        )
    return _SSL_CONTEXTS[key]


def read_evn_branches_file(file_path=EVN_BRANCHES_FILE):
    """Read EVN branches file synchronously"""
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


async def async_load_evn_branches(hass: HomeAssistant) -> dict[str, str] | None:
    """Load evn_branches.json một lần duy nhất (không block event loop)."""
    global _BRANCHES_CACHE
    if _BRANCHES_CACHE is None:
        try:
            _BRANCHES_CACHE = await hass.async_add_executor_job(read_evn_branches_file)
        except Exception as ex:
            _LOGGER.error("Error loading EVN branch info: %s", ex)
            return None
    return _BRANCHES_CACHE


def _pick(items: list, back: int):
    """Phần tử thứ `back` tính từ cuối; nếu list ngắn hơn thì lấy phần tử đầu."""
    return items[-back] if len(items) >= back else items[0]


def _num(value) -> float:
    """Chuyển số dạng '1,234.5' thành float."""
    return float(str(value).replace(",", ""))


def _vn_num(value: str) -> float:
    """Chuyển số kiểu Việt Nam '1.234,5' thành float."""
    return float(value.replace(".", "").replace(",", "."))

class EVNAPI:
    def __init__(self, hass: HomeAssistant, is_new_session=False):
        """Construct EVNAPI wrapper."""
        self.hass = hass  # Store hass instance
        self._session = (
            async_create_clientsession(hass)
            if is_new_session
            else async_get_clientsession(hass)
        )
        self._evn_area = {}

    async def login(self, evn_area, username, password, customer_id) -> str:
        """Try login into EVN corresponding with different EVN areas"""

        self._evn_area = evn_area

        if (username is None) or (password is None):
            return CONF_ERR_UNKNOWN

        name = evn_area.get("name")

        if name == EVN_NAME.SPC:
            return await self.login_evnspc(username, password, customer_id)

        login_fn = {
            EVN_NAME.HCMC: self.login_evnhcmc,
            EVN_NAME.HANOI: self.login_evnhanoi,
            EVN_NAME.CPC: self.login_evncpc,
            EVN_NAME.NPC: self.login_evnnpc,
        }.get(name)

        if login_fn is None:
            return CONF_ERR_UNKNOWN

        return await login_fn(username, password)

    async def request_update(
        self, evn_area: Area, username, password, customer_id, monthly_start=None
    ) -> dict[str, Any]:
        """Request new update from EVN Server, corresponding with the last session"""

        self._evn_area = evn_area

        name = evn_area.get("name")
        fetch_data = {}

        if name == EVN_NAME.CPC:
            # EVNCPC trả sẵn today/yesterday/this-month -> không cần khoảng ngày
            fetch_data = await self.request_update_evncpc(customer_id)

        elif name in (EVN_NAME.HANOI, EVN_NAME.HCMC, EVN_NAME.SPC, EVN_NAME.NPC):
            from_date, to_date = generate_datetime(monthly_start, offset=1)

            if name == EVN_NAME.HANOI:
                fetch_data = await self.request_update_evnhanoi(
                    username, password, customer_id, from_date, to_date
                )
            elif name == EVN_NAME.HCMC:
                fetch_data = await self.request_update_evnhcmc(
                    username, password, customer_id, from_date, to_date
                )
            elif name == EVN_NAME.SPC:
                fetch_data = await self.request_update_evnspc(
                    customer_id, from_date, to_date
                )
            else:
                fetch_data = await self.request_update_evnnpc(
                    customer_id, from_date, to_date
                )

        if not fetch_data:
            _LOGGER.error("Unsupported EVN area: %s", name)
            return {"status": CONF_ERR_UNKNOWN, "data": "Unsupported EVN area"}

        if fetch_data.get("status") == CONF_SUCCESS:
            return formatted_result(fetch_data)

        return fetch_data

    async def login_evnhanoi(self, username, password) -> str:
        """Create EVN login session corresponding with EVNHANOI Endpoint"""

        headers = {
            "User-Agent": UA_BROWSER,
            "Accept": "application/json",
            "Connection": "keep-alive",
        }

        payload = {
            "username": username,
            "password": password,
            "client_id": "httplocalhost4500",
            "client_secret": "secret",
            "grant_type": "password",
        }

        resp = await self._session.post(
            url=self._evn_area.get("evn_login_url"), data=payload, headers=headers
        )

        status, resp_json = await json_processing(resp)
        if status != CONF_SUCCESS:
            return status

        if ("error" in resp_json) and (resp_json["error"] == "invalid_grant"):
            return CONF_ERR_INVALID_AUTH

        elif "access_token" in resp_json:
            self._evn_area["access_token"] = resp_json["access_token"]
            if "expires_in" in resp_json:
                expires_in = resp_json["expires_in"]
                self._evn_area["token_expiry"] = time.time() + expires_in
            return CONF_SUCCESS

        _LOGGER.error("Error while logging in EVN Endpoints: %s", resp_json)
        return CONF_ERR_UNKNOWN

    async def login_evnhcmc(self, username, password) -> str:
        """Create EVN login session corresponding with EVNHCMC Endpoint"""

        headers = {
            "User-Agent": UA_BROWSER,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        payload = {"u": username, "p": password}

        ssl_context = await async_get_ssl_context(self.hass, legacy=True)

        resp = await self._session.post(
            url=self._evn_area.get("evn_login_url"),
            data=payload,
            ssl=ssl_context,
            headers=headers,
        )

        status, resp_json = await json_processing(resp)
        if status != CONF_SUCCESS:
            return status

        login_state = resp_json["state"]

        if login_state in (CONF_SUCCESS, "login"):
            cookie_morsel = resp.cookies.get("evn_session")

            if cookie_morsel and cookie_morsel.value:
                self._evn_area["evn_session"] = cookie_morsel.value

                expires_str = cookie_morsel.get("expires")
                if expires_str:
                    try:
                        self._evn_area["expires"] = parser.parse(
                            expires_str
                        ).replace(tzinfo=timezone.utc)
                    except (ValueError, OverflowError):
                        self._evn_area.pop("expires", None)
                else:
                    self._evn_area.pop("expires", None)

                _LOGGER.debug("EVNHCMC login successful")
                return CONF_SUCCESS

        _LOGGER.error("Unable to login into EVN Endpoint: %s", resp_json)
        return CONF_ERR_INVALID_AUTH

    async def login_evnnpc(self, username, password) -> str:
        """Create EVN login session corresponding with EVNNPC Endpoint"""

        payload = {"username": username, "password": password}

        auth_header = base64.b64encode(
            (
                "A21FA5C-34BE-42D7-AE70-8BF03C1EE540:026A64EF-2A91-4973-AA20-6E8A2B66D560"
            ).encode()
        ).decode()

        headers = {
            "User-Agent": UA_NPC,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Authorization": f"Basic {auth_header}",
        }

        ssl_context = await async_get_ssl_context(self.hass, legacy=True)

        resp = await self._session.post(
            url=self._evn_area.get("evn_login_url"),
            data=payload,
            headers=headers,
            ssl=ssl_context,
        )

        status, resp_json = await json_processing(resp)
        if status != CONF_SUCCESS:
            return status

        if not (
            "message" in resp_json and resp_json["message"] == "Login successfully."
        ):
            return CONF_ERR_INVALID_AUTH

        self._evn_area["access_token"] = resp_json["access_token"]
        return CONF_SUCCESS

    async def login_evncpc(self, username, password) -> str:
        """Create EVN login session corresponding with EVNCPC Endpoint"""

        payload = {
            "username": username,
            "password": password,
            "scope": "CSKH",
            "grant_type": "password",
        }

        basic_auth = "CSKH_Swagger:1q2w3e*"
        auth_header = base64.b64encode(basic_auth.encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "User-Agent": UA_BROWSER,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        resp = await self._session.post(
            url=self._evn_area.get("evn_login_url"), data=payload, headers=headers
        )

        status, resp_json = await json_processing(resp)
        if status != CONF_SUCCESS:
            return status

        if ("error" in resp_json) and (resp_json["error"] == "invalid_grant"):
            return CONF_ERR_INVALID_AUTH

        elif "access_token" in resp_json:
            self._evn_area["access_token"] = resp_json["access_token"]
            return CONF_SUCCESS

        _LOGGER.error("Error while logging in EVN Endpoints: %s", resp_json)
        return CONF_ERR_UNKNOWN

    async def login_evnspc(self, username, password, customer_id) -> str:
        """Create EVN login session corresponding with EVNSPC Endpoint"""

        payload = {
            "strUsername": username,
            "strPassword": password,
            "strDeviceID": customer_id,
        }

        headers = {
            "User-Agent": UA_SPC,
            "Accept-Language": "vi-vn",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Content-Type": "application/json; charset=utf-8",
        }

        resp = await self._session.post(
            url=self._evn_area.get("evn_login_url"),
            data=json.dumps(payload),
            headers=headers,
            ssl=False,
        )

        status, resp_json = await json_processing(resp)

        if status != CONF_SUCCESS:
            return status

        if not ("maKH" in resp_json and "token" in resp_json):
            return CONF_ERR_UNKNOWN

        if resp_json["maKH"] == "":
            return CONF_ERR_INVALID_AUTH

        self._evn_area["access_token"] = resp_json["token"]
        return CONF_SUCCESS

    async def request_update_evnhanoi(
        self, username, password, customer_id, from_date, to_date, last_index="001"
    ):
        """Request new update from EVNHANOI Server"""

        if self.is_token_expired():
            login_status = await self.login_evnhanoi(username, password)
            if login_status != CONF_SUCCESS:
                raise ConfigEntryNotReady("Token expired and failed to reauthenticate")

        headers = {
            "Authorization": f"Bearer {self._evn_area.get('access_token')}",
            "User-Agent": UA_BROWSER,
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }

        data = {
            "maDiemDo": f"{customer_id}{last_index}",
            "maDonVi": f"{customer_id[0:6]}",
            "maXacThuc": "EVNHN",
            "ngayDau": from_date,
            "ngayCuoi": to_date,
        }

        ssl_context = await async_get_ssl_context(self.hass)

        resp = await self._session.post(
            url=self._evn_area.get("evn_data_url"),
            data=json.dumps(data),
            headers=headers,
            ssl=ssl_context,
        )

        status, resp_json = await json_processing(resp)

        if status != CONF_SUCCESS:
            return resp_json

        if resp_json.get("isError"):

            if resp_json.get("code") == 400:

                if last_index == "001":
                    return await self.request_update_evnhanoi(
                        username, password, customer_id, from_date, to_date, last_index="1"
                    )

                return {"status": CONF_ERR_INVALID_ID, "data": resp_json}

            _LOGGER.error("Cannot request new data from EVN Server: %s", resp_json)

            return {"status": resp_json.get("code"), "data": resp_json}

        sub_data = resp_json["data"]["chiSoNgay"]

        first, last = sub_data[0], sub_data[-1]
        prev, prev2 = _pick(sub_data, 2), _pick(sub_data, 3)

        from_date = parser.parse(first["ngay"], dayfirst=True)
        to_date = parser.parse(last["ngay"], dayfirst=True) - timedelta(days=1)
        previous_date = parser.parse(prev["ngay"], dayfirst=True) - timedelta(days=1)

        econ_total_new = round(float(last["sg"]), 2)
        econ_total_old = round(float(first["sg"]), 2)
        econ_daily_new = round(float(last["sg"]) - float(prev["sg"]), 2)
        econ_daily_old = round(float(prev["sg"]) - float(prev2["sg"]), 2)

        fetched_data = {
            "status": CONF_SUCCESS,
            ID_ECON_TOTAL_OLD: econ_total_old,
            ID_ECON_TOTAL_NEW: econ_total_new,
            ID_ECON_DAILY_OLD: econ_daily_old,
            ID_ECON_DAILY_NEW: econ_daily_new,
            ID_ECON_MONTHLY_NEW: round(econ_total_new - econ_total_old, 2),
            "to_date": to_date.date(),
            "from_date": from_date.date(),
            "previous_date": previous_date.date(),
        }

        data = {
            "maKhachHang": customer_id,
            "maDonViQuanLy": f"{customer_id[0:6]}",
        }

        resp = await self._session.post(
            url=self._evn_area.get("evn_payment_url"),
            data=json.dumps(data),
            headers=headers,
            ssl=ssl_context,
        )
        status, resp_json = await json_processing(resp)

        payment_status = CONF_ERR_UNKNOWN
        m_payment_status = 0

        if status == CONF_SUCCESS and not resp_json["isError"]:
            debts = resp_json["data"]["listThongTinNoKhachHangVm"]
            if debts:
                payment_status = STATUS_PAYMENT_NEEDED
                m_payment_status = int(debts[0]["tongTien"].replace(".", ""))
            else:
                payment_status = STATUS_N_PAYMENT_NEEDED

        fetched_data.update(
            {ID_PAYMENT_NEEDED: payment_status, ID_M_PAYMENT_NEEDED: m_payment_status}
        )

        return fetched_data

    def is_token_expired(self) -> bool:
        expiry_time = self._evn_area.get("token_expiry", 0)
        return time.time() > expiry_time

    async def request_update_evnhcmc(self, username, password, customer_id, from_date, to_date):
        """Request new update from EVNHCMC Server"""

        expires = self._evn_area.get("expires")

        if not isinstance(expires, datetime) or datetime.now(tz=timezone.utc) >= expires:
            _LOGGER.debug("EVNHCMC session missing/expired, logging in again")
            if await self.login_evnhcmc(username, password) != CONF_SUCCESS:
                raise ConfigEntryNotReady("Session expired and failed to reauthenticate")

        headers = {
            "User-Agent": UA_BROWSER,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cookie": f"evn_session={self._evn_area.get('evn_session')}",
        }

        ssl_context = await async_get_ssl_context(self.hass)

        resp = await self._session.post(
            url=self._evn_area.get("evn_data_url"),
            data={
                "input_makh": customer_id,
                "input_tungay": from_date,
                "input_denngay": to_date,
            },
            ssl=ssl_context,
            headers=headers,
        )
        status, resp_json = await json_processing(resp)

        if status != CONF_SUCCESS:
            return resp_json

        state = resp_json["state"]

        if state != CONF_SUCCESS:
            if state == "error_login":
                return {"status": CONF_ERR_INVALID_AUTH, "data": resp.status}

            _LOGGER.error(
                f"Cannot request new data from EVN Server for customer ID: {customer_id}\n{resp_json}"
            )
            return {"status": state, "data": resp_json}

        days = resp_json["data"]["sanluong_tungngay"]
        first, last = days[0], days[-1]
        latest, prev = _pick(days, 2), _pick(days, 3)

        from_date = strip_date_range(first["ngayFull"])
        to_date = strip_date_range(latest["ngayFull"])
        previous_date = strip_date_range(prev["ngayFull"])

        econ_total_new = round(_num(last["tong_p_giao"]), 2)
        econ_total_old = round(_num(first["tong_p_giao"]), 2)

        fetched_data = {
            "status": CONF_SUCCESS,
            ID_ECON_TOTAL_OLD: econ_total_old,
            ID_ECON_TOTAL_NEW: econ_total_new,
            ID_ECON_DAILY_NEW: round(_num(latest["Tong"]), 2),
            ID_ECON_DAILY_OLD: round(_num(prev["Tong"]), 2),
            ID_ECON_MONTHLY_NEW: round(econ_total_new - econ_total_old, 2),
            "to_date": to_date.date(),
            "from_date": from_date.date(),
            "previous_date": previous_date.date(),
        }

        resp = await self._session.post(
            url=self._evn_area.get("evn_payment_url"),
            data={"input_makh": customer_id},
            ssl=ssl_context,
            headers=headers,
        )
        status, resp_json = await json_processing(resp)

        payment_status = CONF_ERR_UNKNOWN
        m_payment_status = 0

        if status == CONF_SUCCESS:
            pay_data = resp_json["data"]
            is_no = pay_data.get("isNo")

            if is_no == 1:
                payment_status = STATUS_PAYMENT_NEEDED
                if "info_no" in pay_data:
                    m_payment_status = int(
                        pay_data["info_no"].get("TONG_TIEN").replace(".", "")
                    )
            elif is_no == 0:
                payment_status = STATUS_N_PAYMENT_NEEDED

        fetched_data.update(
            {ID_PAYMENT_NEEDED: payment_status, ID_M_PAYMENT_NEEDED: m_payment_status}
        )

        return fetched_data

    async def request_update_evnnpc(
        self, customer_id, from_date, to_date, last_index="001"
    ):
        """Request new update from EVNNPC Server"""

        payload = {
            "ma": f"{customer_id}{last_index}",
            "start_intime": from_date.replace("/", "-"),
            "stop_intime": to_date.replace("/", "-"),
        }

        headers = {
            "User-Agent": UA_NPC,
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "Authorization": f"Bearer {self._evn_area.get('access_token')}",
        }

        ssl_context = await async_get_ssl_context(self.hass)

        resp = await self._session.post(
            url=self._evn_area.get("evn_data_url"),
            data=json.dumps(payload),
            headers=headers,
            ssl=ssl_context,
        )

        status, resp_json = await json_processing(resp)
        if status != CONF_SUCCESS:
            return resp_json

        # Dữ liệu NPC sắp xếp mới nhất trước: [0] = ngày gần nhất, [-1] = đầu kỳ
        valid_info = [
            item
            for item in resp_json
            if item.get("GHI_CHU") == "Sản lượng điện tiêu thụ của khách hàng"
            and item.get("LOAI_CHI_SO") == "P"
        ]

        if not valid_info:
            return {
                "status": CONF_ERR_NO_MONITOR,
                "data": str(resp_json[0]),
            }

        newest, oldest = valid_info[0], valid_info[-1]
        second = valid_info[1] if len(valid_info) > 1 else newest

        from_date = parser.parse(oldest["THOI_GIAN_BAT_DAU"])
        to_date = parser.parse(newest["THOI_GIAN_BAT_DAU"])
        previous_date = parser.parse(second["THOI_GIAN_BAT_DAU"])

        econ_total_new = float(newest["CHI_SO_KET_THUC"])
        econ_total_old = float(oldest["CHI_SO_BAT_DAU"])

        fetched_data = {
            "status": CONF_SUCCESS,
            ID_ECON_TOTAL_NEW: round(econ_total_new, 2),
            ID_ECON_TOTAL_OLD: round(econ_total_old, 2),
            ID_ECON_DAILY_NEW: round(float(newest["SAN_LUONG"]), 2),
            ID_ECON_DAILY_OLD: round(float(second["SAN_LUONG"]), 2),
            ID_ECON_MONTHLY_NEW: round(econ_total_new - econ_total_old, 2),
            "from_date": from_date.date(),
            "to_date": to_date.date(),
            "previous_date": previous_date.date(),
        }

        resp = await self._session.get(
            url=f'{self._evn_area.get("evn_payment_url")}{customer_id}',
            headers=headers,
            ssl=ssl_context,
        )
        status, resp_json = await json_processing(resp)

        payment_status = CONF_ERR_UNKNOWN
        m_payment_status = 0

        if status == CONF_SUCCESS and "data" in resp_json:
            invoices = (resp_json["data"].get("customerInfo") or {}).get("invoice")

            if invoices:
                if invoices[0].get("paid"):
                    payment_status = STATUS_N_PAYMENT_NEEDED
                else:
                    payment_status = STATUS_PAYMENT_NEEDED
                    m_payment_status = invoices[0].get("paymentTotalAmount")

        fetched_data.update(
            {
                ID_PAYMENT_NEEDED: payment_status,
                ID_M_PAYMENT_NEEDED: m_payment_status,
            }
        )

        return fetched_data

    async def request_update_evncpc(self, customer_id):
        """Request new update from EVNCPC Server"""

        headers = {
            "Authorization": f"Bearer {self._evn_area.get('access_token')}",
            "User-Agent": UA_BROWSER,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        resp = await self._session.get(
            url=f"{self._evn_area.get('evn_data_url')}{customer_id}",
            headers=headers,
        )

        status, resp_json = await json_processing(resp)

        if status != CONF_SUCCESS:
            return resp_json

        consumption = resp_json["electricConsumption"]
        fetched_data = {
            "status": CONF_SUCCESS,
            ID_ECON_DAILY_NEW: round(float(consumption["electricConsumptionToday"]), 2),
            ID_ECON_DAILY_OLD: round(
                float(consumption["electricConsumptionYesterday"]), 2
            ),
            ID_ECON_MONTHLY_NEW: round(
                float(consumption["electricConsumptionThisMonth"]), 2
            ),
        }

        resp = await self._session.get(
            url=f"{self._evn_area.get('evn_payment_url')}{customer_id}",
            headers=headers,
        )

        status, resp_json = await json_processing(resp)

        if status != CONF_SUCCESS:
            return resp_json

        m_payment_status = 0
        payment_status = CONF_ERR_UNKNOWN

        info = resp_json["response"]

        if resp_json["status"] == 0 and "tinhTrangThanhToan" in info:
            if info["tinhTrangThanhToan"] == "Đã thanh toán":
                payment_status = STATUS_N_PAYMENT_NEEDED
            else:
                payment_status = STATUS_PAYMENT_NEEDED
                if "tienHoaDon" in info:
                    m_payment_status = int(
                        info["tienHoaDon"].replace(".", "").replace("đ", "")
                    )

        current_einfo = info.get("dienNangHienTai")

        try:
            to_date = datetime.strptime(
                current_einfo.get("thoiDiem"), "%Hh%M - %d/%m/%Y"
            ).date()
        except Exception:
            to_date = datetime.now().date()

        fetched_data.update(
            {
                ID_PAYMENT_NEEDED: payment_status,
                ID_M_PAYMENT_NEEDED: m_payment_status,
                ID_ECON_TOTAL_NEW: round(_vn_num(current_einfo.get("chiSo")), 2),
                ID_ECON_TOTAL_OLD: round(_vn_num(info.get("chiSoCuoiKy")), 2),
                "to_date": to_date,
                "previous_date": to_date - timedelta(days=1),
            }
        )

        return fetched_data

    async def request_update_evnspc(
        self, customer_id, from_date, to_date, last_index="001"
    ):
        """Request new update from EVNSPC Server"""

        from_date_str = (parser.parse(from_date, dayfirst=True) - timedelta(days=1)).strftime("%Y%m%d")
        to_date_str = parser.parse(to_date, dayfirst=True).strftime("%Y%m%d")

        headers = {
            "User-Agent": UA_SPC,
            "Authorization": f"Bearer {self._evn_area.get('access_token')}",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "vi-vn",
            "Connection": "keep-alive",
        }

        status, resp_json = await fetch_with_retries(
            url=self._evn_area.get("evn_data_url"),
            headers=headers,
            params={
                "strMaDiemDo": f"{customer_id}{last_index}",
                "strFromDate": from_date_str,
                "strToDate": to_date_str,
            },
            session=self._session,
            api_name="Fetch EVN data"
        )

        if status != CONF_SUCCESS or not resp_json:
            return {
                "status": status if status != CONF_SUCCESS else CONF_ERR_UNKNOWN,
                "data": resp_json,
            }

        first, last = resp_json[0], resp_json[-1]

        from_date = parser.parse(first["strTime"], dayfirst=True) + timedelta(days=1)
        to_date = parser.parse(last["strTime"], dayfirst=True)
        previous_date = parser.parse(_pick(resp_json, 2)["strTime"], dayfirst=True)

        econ_total_old = safe_float(first.get("dGiaoBT"))
        econ_total_new = safe_float(last.get("dGiaoBT"))

        fetched_data = {
            "status": CONF_SUCCESS,
            ID_ECON_TOTAL_OLD: round(econ_total_old, 2),
            ID_ECON_TOTAL_NEW: round(econ_total_new, 2),
            ID_ECON_DAILY_NEW: round(safe_float(last.get("dSanLuongBT")), 2),
            ID_ECON_DAILY_OLD: round(
                safe_float(resp_json[-2].get("dSanLuongBT"))
                if len(resp_json) > 1
                else 0.0,
                2,
            ),
            ID_ECON_MONTHLY_NEW: round(econ_total_new - econ_total_old, 2),
            "to_date": to_date.date(),
            "from_date": from_date.date(),
            "previous_date": previous_date.date(),
        }

        status, resp_json = await fetch_with_retries(
            url=self._evn_area.get("evn_payment_url"),
            headers=headers,
            params={
                "strMaKH": f"{customer_id}",
            },
            session=self._session,
            api_name="Payment data"
        )

        if status == CONF_SUCCESS and isinstance(resp_json, list) and resp_json:
            fetched_data[ID_PAYMENT_NEEDED] = STATUS_PAYMENT_NEEDED
            fetched_data[ID_M_PAYMENT_NEEDED] = int(resp_json[0].get("lTongTien", 0))
        else:
            fetched_data[ID_PAYMENT_NEEDED] = (
                STATUS_N_PAYMENT_NEEDED if status == CONF_EMPTY else CONF_ERR_UNKNOWN
            )
            fetched_data[ID_M_PAYMENT_NEEDED] = 0

        status, resp_json = await fetch_with_retries(
            url=self._evn_area.get("evn_loadshedding_url"),
            headers=headers,
            params={
                "strMaKH": f"{customer_id}",
            },
            session=self._session,
            api_name="EVN loadshedding data"
        )

        if status == CONF_SUCCESS and isinstance(resp_json, list) and resp_json:
            fetched_data[ID_LOADSHEDDING] = resp_json[0].get("strThoiGianMatDien")
        else:
            fetched_data[ID_LOADSHEDDING] = (
                STATUS_LOADSHEDDING if status == CONF_EMPTY else CONF_ERR_UNKNOWN
            )

        return fetched_data


_HTTP_ERROR_STATUS = {
    400: CONF_ERR_INVALID_AUTH,
    401: CONF_ERR_INVALID_AUTH,
    405: CONF_ERR_NOT_SUPPORTED,
}


async def json_processing(resp):
    """Parse an aiohttp response -> (status, json | error dict)."""

    if resp.status != 200:
        state = _HTTP_ERROR_STATUS.get(resp.status, CONF_ERR_CANNOT_CONNECT)
        if state == CONF_ERR_CANNOT_CONNECT:
            _LOGGER.error(
                "Cannot connect to EVN Server while requesting new data: status code %s",
                resp.status,
            )
        resp.release()
        return state, {"status": state, "data": resp.status}

    try:
        resp_json = json.loads(await resp.text(), strict=False)
    except Exception as error:
        _LOGGER.error(
            "Unable to fetch data from EVN Server while requesting new data: %s", error
        )
        return CONF_ERR_UNKNOWN, {"status": CONF_ERR_UNKNOWN, "data": error}

    if not resp_json:
        return CONF_EMPTY, {"status": CONF_EMPTY, "data": resp_json}

    return CONF_SUCCESS, resp_json


def formatted_result(raw_data: dict) -> dict:
    res = {}
    time_obj = datetime.now()

    res["status"] = CONF_SUCCESS

    res[ID_ECON_TOTAL_NEW] = {
        "value": raw_data[ID_ECON_TOTAL_NEW],
        "info": raw_data["to_date"],
    }

    res[ID_ECON_TOTAL_OLD] = {
        "value": raw_data[ID_ECON_TOTAL_OLD],
    }

    if raw_data[ID_ECON_MONTHLY_NEW] is not None:
        res[ID_ECON_MONTHLY_NEW] = {
            "value": raw_data[ID_ECON_MONTHLY_NEW],
        }
        res[ID_ECOST_MONTHLY_NEW] = {
            "value": calc_ecost(raw_data[ID_ECON_MONTHLY_NEW]),
        }

    monthly_total = raw_data.get(ID_ECON_MONTHLY_NEW)

    if raw_data[ID_ECON_DAILY_NEW] is not None:
        if raw_data["to_date"] == time_obj.date():
            info = "hôm nay"
        elif raw_data["to_date"] == (time_obj - timedelta(days=1)).date():
            info = "hôm qua"
        else:
            info = f'ngày {raw_data["to_date"].strftime("%d/%m")}'

        if monthly_total is not None:
            cumulative_before_new = max(0.0, monthly_total - raw_data[ID_ECON_DAILY_NEW])
            ecost_daily_new = calc_ecost_delta(cumulative_before_new, monthly_total)
        else:
            ecost_daily_new = calc_ecost(raw_data[ID_ECON_DAILY_NEW])

        res[ID_ECON_DAILY_NEW] = {"value": raw_data[ID_ECON_DAILY_NEW], "info": info}
        res[ID_ECOST_DAILY_NEW] = {
            "value": ecost_daily_new,
            "info": info,
        }

    if raw_data[ID_ECON_DAILY_OLD] is not None:
        if raw_data["previous_date"] == (time_obj - timedelta(days=2)).date():
            info = "hôm kia"
        elif raw_data["previous_date"] == (time_obj - timedelta(days=1)).date():
            info = "hôm qua"
        else:
            info = f'ngày {raw_data["previous_date"].strftime("%d/%m")}'

        if monthly_total is not None and raw_data[ID_ECON_DAILY_NEW] is not None:
            cumulative_through_old = max(
                0.0, monthly_total - raw_data[ID_ECON_DAILY_NEW]
            )
            cumulative_before_old = max(
                0.0, cumulative_through_old - raw_data[ID_ECON_DAILY_OLD]
            )
            ecost_daily_old = calc_ecost_delta(cumulative_before_old, cumulative_through_old)
        else:
            ecost_daily_old = calc_ecost(raw_data[ID_ECON_DAILY_OLD])

        res[ID_ECON_DAILY_OLD] = {"value": raw_data[ID_ECON_DAILY_OLD], "info": info}
        res[ID_ECOST_DAILY_OLD] = {
            "value": ecost_daily_old,
            "info": info,
        }

    payment = raw_data[ID_PAYMENT_NEEDED]
    res[ID_PAYMENT_NEEDED] = {
        "value": payment if payment in _PAYMENT_ICONS else None,
        "info": _PAYMENT_ICONS.get(payment, "mdi:comment-question-outline"),
    }

    m_payment = raw_data.get(ID_M_PAYMENT_NEEDED) or 0
    res[ID_M_PAYMENT_NEEDED] = {
        "value": str(m_payment),
        "info": (
            "mdi:alert-circle-outline"
            if float(m_payment) > 0
            else "mdi:checkbox-marked-circle-outline"
        ),
    }

    loadshedding = raw_data.get(ID_LOADSHEDDING)
    if loadshedding is None:
        formatted_content = "Không hỗ trợ"
    else:
        formatted_content = format_loadshedding(loadshedding)

    res[ID_LOADSHEDDING] = {
        "value": formatted_content,
        "info": "mdi:transmission-tower-off",
    }

    from_date = raw_data.get(ID_FROM_DATE) or time_obj.replace(day=1)
    res[ID_FROM_DATE] = {"value": from_date.strftime("%d/%m/%Y")}
    res[ID_TO_DATE] = {"value": raw_data["to_date"].strftime("%d/%m/%Y")}
    res[ID_LATEST_UPDATE] = {"value": time_obj.astimezone()}

    return res


_PAYMENT_ICONS = {
    STATUS_PAYMENT_NEEDED: "mdi:comment-alert-outline",
    STATUS_N_PAYMENT_NEEDED: "mdi:comment-check-outline",
}


def generate_datetime(monthly_start=1, offset=0):
    """Generate Datetime as string for requesting data purposes"""

    # Example:

    #   EVNSPC
    #   if offset == 1 means:
    #       When requesting to EVN endpoints for date 10/09/2022,
    #       the e-data returned from server would contain:
    #           - Total e-consumption data on 09/09/2022
    #           - E-monitor value at 23:59 09/09/2022

    #   if offset == 0 means:
    #       When requesting to EVN endpoints for date 10/09/2022,
    #       the e-data returned from server would contain:
    #           - Latest e-consumption data on 10/09/2022
    #           - E-monitor value at 23:59 10/09/2022

    now = datetime.now()
    start_day = monthly_start - 1 + offset

    to_date = (now - timedelta(days=1 - offset)).strftime("%d/%m/%Y")

    # Đã qua ngày chốt kỳ trong tháng này -> kỳ bắt đầu từ tháng này,
    # ngược lại kỳ bắt đầu từ tháng trước (tháng 1 -> tháng 12 năm trước).
    if now.day > monthly_start:
        year, month = now.year, now.month
    elif now.month > 1:
        year, month = now.year, now.month - 1
    else:
        year, month = now.year - 1, 12

    return f"{start_day:02d}/{month:02d}/{year}", to_date


# (ngưỡng dưới, ngưỡng trên, đơn giá) — tính một lần từ VIETNAM_ECOST_STAGES
_ECOST_TIERS = tuple(
    zip(
        sorted(VIETNAM_ECOST_STAGES),
        sorted(VIETNAM_ECOST_STAGES)[1:] + [float("inf")],
        (VIETNAM_ECOST_STAGES[k] for k in sorted(VIETNAM_ECOST_STAGES)),
    )
)


def calc_ecost(kwh: float) -> str:
    """Calculate electric cost based on e-consumption"""

    total_price = 0.0

    for lower, upper, price in _ECOST_TIERS:
        if kwh <= lower:
            break
        total_price += (min(kwh, upper) - lower) * price

    return str(int(round((total_price / 100) * (100 + VIETNAM_ECOST_VAT))))


def calc_ecost_delta(prior_kwh: float, new_total_kwh: float) -> str:
    """Calculate the marginal cost of consumption added on top of prior_kwh,
    based on the progressive monthly tier the new total falls into."""

    prior_cost = int(calc_ecost(prior_kwh))
    total_cost = int(calc_ecost(new_total_kwh))

    return str(max(0, total_cost - prior_cost))


def safe_float(value, default=0.0):
    try:
        return float(str(value).replace(",", "")) if value is not None else default
    except ValueError:
        return default


def format_loadshedding(raw_value: str) -> str:
    try:
        if not raw_value or "đến" not in raw_value:
            return STATUS_LOADSHEDDING

        start, end = raw_value.replace("từ ", "").replace(" ngày", "").split("đến")
        start = start.strip().split()
        end = end.strip().split()
        if len(start) != 2 or len(end) != 2:
            return STATUS_LOADSHEDDING

        (start_time, start_date), (end_time, end_date) = start, end

        return (
            f"{start_time[:-3]} {start_date[:-5]} - {end_time[:-3]} {end_date[:-5]}"
        )

    except Exception:
        return STATUS_LOADSHEDDING


def strip_date_range(date_str):
    if "đến" in date_str:
        date_str = date_str.split("đến")[1]
    return parser.parse(date_str.strip(), dayfirst=True)


# Lỗi "cố định" — thử lại cũng vô ích
_NO_RETRY_STATUS = (CONF_ERR_INVALID_AUTH, CONF_ERR_NOT_SUPPORTED)


async def fetch_with_retries(
    url, headers, params, max_retries=3, session=None, api_name="API"
):
    """Fetch data with retry mechanism (GET, có backoff giữa các lần thử)."""
    status = CONF_ERR_CANNOT_CONNECT
    resp_json = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = await session.get(url=url, headers=headers, params=params, ssl=False)
            status, resp_json = await json_processing(resp)

            if status == CONF_EMPTY:
                return CONF_EMPTY, []

            if status == CONF_SUCCESS:
                return status, resp_json

            _LOGGER.warning(
                "Attempt %s/%s failed for %s: %s", attempt, max_retries, api_name, resp_json
            )

            if status in _NO_RETRY_STATUS:
                break

        except Exception as e:
            status = CONF_ERR_UNKNOWN
            resp_json = str(e)
            _LOGGER.warning(
                "Attempt %s/%s for %s encountered an error: %s",
                attempt,
                max_retries,
                api_name,
                e,
            )

        if attempt < max_retries:
            await asyncio.sleep(attempt)

    _LOGGER.error("Failed to fetch data of %s after %s attempts.", api_name, attempt)
    return status, resp_json


def get_evn_info_sync(customer_id: str, branches_data=None):
    """Synchronous helper to get EVN info"""
    for each_area in VIETNAM_EVN_AREA:
        if not any(pattern in customer_id for pattern in each_area.pattern):
            continue

        evn_branch = "Unknown"
        if branches_data:
            # Giữ nguyên hành vi cũ: mã khớp cuối cùng được ưu tiên
            for evn_id, branch_name in branches_data.items():
                if evn_id in customer_id:
                    evn_branch = branch_name

        return {
            "status": CONF_SUCCESS,
            "customer_id": customer_id,
            "evn_area": asdict(each_area),
            "evn_name": each_area.name,
            "evn_location": each_area.location,
            "evn_branch": evn_branch,
        }

    return {"status": CONF_ERR_NOT_SUPPORTED}
