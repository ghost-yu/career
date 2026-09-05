from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd

DEFAULT_FIELD_MAP: dict[str, str] = {
    "职位名称": "title",
    "岗位名称": "title",
    "工作地址": "location",
    "工作地点": "location",
    "地址": "location",
    "薪资范围": "salary_range",
    "薪资": "salary_range",
    "公司全称": "company_name",
    "公司名称": "company_name",
    "公司": "company_name",
    "所属行业": "industry",
    "行业": "industry",
    "人员规模": "company_size",
    "公司规模": "company_size",
    "企业性质": "company_type",
    "公司类型": "company_type",
    "职位编码": "job_code",
    "岗位编码": "job_code",
    "职位描述": "description",
    "岗位描述": "description",
    "岗位详情": "description",
    "公司简介": "company_intro",
    "公司详情": "company_intro",
    "更新日期": "updated_date",
    "更新时间": "updated_date",
    "岗位来源地址": "source_url",
    "职位来源地址": "source_url",
}

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\u3000", " ").strip()


def coerce_sheet_name(value: Any) -> str | int | None:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    if raw == "":
        return 0
    if raw.lower() in {"none", "null", "all"}:
        return None
    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        try:
            return int(raw)
        except Exception:
            pass
    return raw


def _read_excel_with_engine(path: str, *, engine: str, sheet_name: str | int | None) -> pd.DataFrame:
    df = pd.read_excel(path, engine=engine, sheet_name=sheet_name, dtype=object)
    if isinstance(df, dict):
        first_key = next(iter(df.keys()))
        df = df[first_key]
    return df.where(df.notna(), None)


def _read_excel_via_soffice(path: str, *, sheet_name: str | int | None) -> pd.DataFrame:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(td_path), path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        converted = td_path / (Path(path).stem + ".xlsx")
        if not converted.exists():
            raise RuntimeError("使用 LibreOffice 转换 Excel 失败。")
        return _read_excel_with_engine(str(converted), engine="openpyxl", sheet_name=sheet_name)


def _sheet_names_with_engine(path: str, *, engine: str) -> list[str]:
    xf = pd.ExcelFile(path, engine=engine)
    return list(xf.sheet_names)


def _has_soffice() -> bool:
    return shutil.which("soffice") is not None


def list_excel_sheets(path: str | os.PathLike[str]) -> list[str]:
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    errors: list[str] = []
    engines: list[str] = []
    if ext == ".xlsx":
        engines = ["openpyxl", "calamine"]
    elif ext == ".xls":
        engines = ["xlrd", "calamine"]
    else:
        return []
    for engine in engines:
        try:
            return _sheet_names_with_engine(path, engine=engine)
        except Exception as exc:
            errors.append(f"{engine}: {exc}")
    if _has_soffice():
        try:
            return _sheet_names_with_engine(_convert_excel_via_soffice(path), engine="openpyxl")
        except Exception as exc:
            errors.append(f"soffice: {exc}")
    raise RuntimeError("读取工作表失败：" + " | ".join(errors))


def _convert_excel_via_soffice(path: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(td_path), path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        converted = td_path / (Path(path).stem + ".xlsx")
        if not converted.exists():
            raise RuntimeError("使用 LibreOffice 转换 Excel 失败。")
        persisted = td_path / (Path(path).stem + "__persist.xlsx")
        converted.replace(persisted)
        return str(persisted)


def read_excel_any(path: str | os.PathLike[str], sheet_name: str | int | None = 0) -> pd.DataFrame:
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    sheet_name = coerce_sheet_name(sheet_name)
    errors: list[str] = []

    if ext == ".xlsx":
        engines = ["openpyxl", "calamine"]
    elif ext == ".xls":
        engines = ["xlrd", "calamine"]
    else:
        raise ValueError(f"unsupported excel file: {ext}")

    for engine in engines:
        try:
            return _read_excel_with_engine(path, engine=engine, sheet_name=sheet_name)
        except Exception as exc:
            errors.append(f"{engine}: {exc}")

    if _has_soffice():
        try:
            return _read_excel_via_soffice(path, sheet_name=sheet_name)
        except Exception as exc:
            errors.append(f"soffice: {exc}")

    raise RuntimeError(
        "读取 Excel 失败，请安装依赖后重试。建议执行：pip install -r backend/requirements.txt。详细原因："
        + " | ".join(errors)
    )


def preview_excel(path: str | os.PathLike[str], sheet_name: str | int | None = 0, sample_rows: int = 5) -> dict[str, Any]:
    df = read_excel_any(path, sheet_name=sheet_name)
    rows = df.head(max(1, int(sample_rows))).to_dict(orient="records")
    return {
        "sheet_name": coerce_sheet_name(sheet_name),
        "sheet_names": list_excel_sheets(path),
        "columns": [str(c) for c in df.columns.tolist()],
        "row_count": int(len(df.index)),
        "sample_rows": rows,
        "mapped_fields": [
            {"source": str(c), "target": DEFAULT_FIELD_MAP.get(_normalize_text(c), "")}
            for c in df.columns.tolist()
        ],
    }


def parse_salary_range(text: str | None) -> Tuple[int | None, int | None, str | None]:
    if not text:
        return None, None, None
    s = _normalize_text(text).lower()
    if not s:
        return None, None, None
    s = s.replace("—", "-").replace("~", "-").replace("至", "-")
    unit = 1
    if "万" in s:
        unit = 10000
    elif "k" in s:
        unit = 1000
    elif "千" in s:
        unit = 1000
    if any(tok in s for tok in ["/年", "年薪", "万/年"]):
        period = "year"
        multiplier = 1 / 12
    elif any(tok in s for tok in ["/天", "/日", "元/天", "元/日"]):
        period = "day"
        multiplier = 21.75
    elif any(tok in s for tok in ["/时", "小时", "元/时"]):
        period = "hour"
        multiplier = 8 * 21.75
    else:
        period = "month"
        multiplier = 1
    nums = [float(x) for x in _NUM_RE.findall(s)]
    if not nums:
        return None, None, period
    if len(nums) == 1:
        v = int(nums[0] * unit * multiplier)
        return v, v, period
    a, b = nums[0], nums[1]
    return int(min(a, b) * unit * multiplier), int(max(a, b) * unit * multiplier), period


def map_row(row: Dict[str, Any], field_map: Dict[str, str] | None = None) -> Dict[str, Any]:
    fm = {**DEFAULT_FIELD_MAP, **(field_map or {})}
    out: Dict[str, Any] = {}
    if "title" in row and "description" in row:
        out = dict(row)
    else:
        for k, v in row.items():
            key = fm.get(_normalize_text(k))
            if key:
                out[key] = v
    if "salary_range" in out and ("salary_min" not in out and "salary_max" not in out):
        smin, smax, period = parse_salary_range(out.get("salary_range"))
        out["salary_min"] = smin
        out["salary_max"] = smax
        out["salary_period"] = period
    if out.get("source_url"):
        out["source_url"] = _normalize_text(out.get("source_url"))
    if out.get("updated_date"):
        out["updated_date"] = _normalize_text(out.get("updated_date"))
    return out
