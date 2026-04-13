"""
query_builder.py
────────────────
Nhận supervisor output (procedures + fields) và sinh câu SQL
tối ưu để truy vấn dữ liệu thủ tục hành chính.

Schema (rag):
  thu_tuc            — bảng chính
  thanh_phan_ho_so   — FK: ma_thu_tuc  (1-N)
  cach_thuc_thuc_hien— FK: ma_thu_tuc  (1-N)
  can_cu_phap_ly     — FK: ma_thu_tuc  (1-N)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re


# ─────────────────────────────────────────────
# Cấu hình schema
# ─────────────────────────────────────────────

# Alias ngắn cho từng bảng
TABLE_ALIASES: dict[str, str] = {
    "thu_tuc":              "tt",
    "thanh_phan_ho_so":     "tphs",
    "cach_thuc_thuc_hien":  "ctth",
    "can_cu_phap_ly":       "ccpl",
}

# Các cột hợp lệ của từng bảng (dùng để validate)
TABLE_COLUMNS: dict[str, set[str]] = {
    "thu_tuc": {
        "ma_thu_tuc", "link_tham_khao", "ten_thu_tuc", "cap_thuc_hien",
        "so_quyet_dinh", "loai_thu_tuc", "linh_vuc", "trinh_tu_thuc_hien",
        "doi_tuong_thuc_hien", "co_quan_thuc_hien", "co_quan_co_tham_quyen",
        "dia_chi_tiep_nhan_hs", "co_quan_duoc_uy_quyen", "co_quan_phoi_hop",
        "ket_qua_thuc_hien", "yeu_cau_dieu_kien", "tu_khoa", "mo_ta",
    },
    "thanh_phan_ho_so": {
        "ma_thanh_phan", "truong_hop", "loai_giay_to",
        "mau_don_to_khai", "so_luong", "ma_thu_tuc",
    },
    "cach_thuc_thuc_hien": {
        "ma_cach_thuc", "hinh_thuc_nop", "thoi_han_giai_quyet",
        "phi_le_phi", "mo_ta", "ma_thu_tuc",
    },
    "can_cu_phap_ly": {
        "ma_can_cu", "so_ky_hieu", "trich_yeu",
        "ngay_ban_hanh", "co_quan_ban_hanh", "ma_thu_tuc",
    },
}

# Các bảng phụ (cần JOIN)
CHILD_TABLES = {"thanh_phan_ho_so", "cach_thuc_thuc_hien", "can_cu_phap_ly"}

# Trường dùng để match tên thủ tục
PROCEDURE_MATCH_COLUMN = "ten_thu_tuc"

# Luôn SELECT ma_thu_tuc để có thể liên kết kết quả
ALWAYS_SELECT = {"thu_tuc": {"ma_thu_tuc", "ten_thu_tuc"}}


# ─────────────────────────────────────────────
# Kiểu dữ liệu
# ─────────────────────────────────────────────

@dataclass
class SupervisorOutput:
    procedures: list[str]
    fields: list[str]           # format: "table.column"
    pipeline: list              # ["qa"] / ["qa","forms"] / ...


@dataclass
class ParsedFields:
    """Kết quả phân tích fields theo từng bảng."""
    by_table: dict[str, set[str]] = field(default_factory=dict)
    invalid: list[str] = field(default_factory=list)


@dataclass
class QueryPlan:
    """Kế hoạch truy vấn được build ra."""
    main_sql: str                        # câu query tổng hợp (LEFT JOIN)
    child_sqls: dict[str, str]           # query riêng cho từng bảng phụ nếu cần
    tables_used: list[str]
    fields_used: dict[str, list[str]]
    warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────
# Bước 1 — Parse & validate fields
# ─────────────────────────────────────────────

def parse_fields(fields: list[str]) -> ParsedFields:
    """
    Tách fields theo bảng, validate tên cột, loại bỏ trùng.
    Tự động thêm các cột bắt buộc (ALWAYS_SELECT).
    """
    result = ParsedFields()

    # Thêm các cột bắt buộc
    for tbl, cols in ALWAYS_SELECT.items():
        result.by_table.setdefault(tbl, set()).update(cols)

    for raw in fields:
        raw = raw.strip()
        parts = raw.split(".")
        if len(parts) != 2:
            result.invalid.append(raw)
            continue

        table, column = parts[0].strip(), parts[1].strip()

        if table not in TABLE_COLUMNS:
            result.invalid.append(raw)
            continue

        if column not in TABLE_COLUMNS[table]:
            result.invalid.append(raw)
            continue

        result.by_table.setdefault(table, set()).add(column)

    return result


# ─────────────────────────────────────────────
# Bước 2 — Xác định chiến lược JOIN
# ─────────────────────────────────────────────

def decide_join_strategy(parsed: ParsedFields) -> dict[str, str]:
    """
    Trả về dict {table: join_type}.
    - thu_tuc luôn là bảng chính (FROM)
    - Các bảng phụ dùng LEFT JOIN
    - Bảng phụ chỉ có nhiều hàng (1-N) sẽ query riêng để tránh row multiplication
    """
    strategy: dict[str, str] = {}

    child_tables_needed = [
        t for t in CHILD_TABLES
        if t in parsed.by_table
    ]

    # Nếu có ≥ 2 bảng phụ → tách query riêng để tránh cartesian explosion
    if len(child_tables_needed) >= 2:
        strategy["__multi_child__"] = "separate"
    else:
        for t in child_tables_needed:
            strategy[t] = "LEFT JOIN"

    return strategy


# ─────────────────────────────────────────────
# Bước 3 — Build SELECT clause
# ─────────────────────────────────────────────

def build_select_clause(
    parsed: ParsedFields,
    tables_in_join: list[str],
    alias_map: dict[str, str],
) -> str:
    parts = []
    for table in tables_in_join:
        if table not in parsed.by_table:
            continue
        alias = alias_map[table]
        for col in sorted(parsed.by_table[table]):
            # Dùng alias để tránh ambiguous nếu hai bảng có cột trùng tên
            parts.append(f"    {alias}.{col}")
    return "SELECT\n" + ",\n".join(parts)


# ─────────────────────────────────────────────
# Bước 4 — Build WHERE clause
# ─────────────────────────────────────────────

def build_where_clause(
    procedures: list[str],
    main_alias: str,
) -> tuple[str, list[str]]:
    """
    Trả về (where_sql, params).
    Dùng parameterized query để tránh SQL injection.
    Hỗ trợ tìm kiếm tương đối (ILIKE) và khớp chính xác (=).
    """
    if not procedures:
        return "", []

    conditions = []
    params = []

    for i, proc in enumerate(procedures):
        proc = proc.strip()
        # Fuzzy match — dùng ILIKE với % để tìm gần đúng
        conditions.append(
            f"    {main_alias}.{PROCEDURE_MATCH_COLUMN} ILIKE ${len(params) + 1}"
        )
        params.append(f"%{proc}%")

    where_sql = "WHERE (\n" + "\n    OR\n".join(conditions) + "\n)"
    return where_sql, params


# ─────────────────────────────────────────────
# Bước 5 — Build JOIN clause
# ─────────────────────────────────────────────

def build_join_clause(
    join_tables: list[str],
    alias_map: dict[str, str],
) -> str:
    lines = []
    main_alias = alias_map["thu_tuc"]
    for table in join_tables:
        if table == "thu_tuc":
            continue
        alias = alias_map[table]
        lines.append(
            f"LEFT JOIN rag.{table} {alias}"
            f" ON {alias}.ma_thu_tuc = {main_alias}.ma_thu_tuc"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Bước 6 — Build query riêng cho bảng phụ
# ─────────────────────────────────────────────

def build_child_query(
    table: str,
    columns: set[str],
    alias_map: dict[str, str],
    procedures: list[str],
    param_offset: int = 1,
) -> tuple[str, list[str]]:
    """
    Query riêng: JOIN với thu_tuc để lọc theo tên thủ tục.
    param_offset: vị trí $N bắt đầu (để ghép chung params nếu cần).
    """
    alias = alias_map[table]
    tt_alias = alias_map["thu_tuc"]

    # Luôn kéo về ma_thu_tuc để join phía client nếu cần
    cols_to_select = sorted(columns | {"ma_thu_tuc"})
    select_parts = [f"    {alias}.{c}" for c in cols_to_select]
    select_sql = "SELECT\n" + ",\n".join(select_parts)

    from_sql = f"FROM rag.{table} {alias}"
    join_sql = (
        f"JOIN rag.thu_tuc {tt_alias}"
        f" ON {tt_alias}.ma_thu_tuc = {alias}.ma_thu_tuc"
    )

    params: list[str] = []
    conditions = []
    for proc in procedures:
        conditions.append(
            f"    {tt_alias}.{PROCEDURE_MATCH_COLUMN} ILIKE ${param_offset + len(params)}"
        )
        params.append(f"%{proc.strip()}%")

    where_sql = ""
    if conditions:
        where_sql = "WHERE (\n" + "\n    OR\n".join(conditions) + "\n)"

    sql = "\n".join(filter(None, [select_sql, from_sql, join_sql, where_sql])) + ";"
    return sql, params


# ─────────────────────────────────────────────
# Entry point — build_query_plan
# ─────────────────────────────────────────────

def build_query_plan(supervisor_output: SupervisorOutput) -> QueryPlan:
    """
    Hàm chính: nhận SupervisorOutput, trả về QueryPlan.
    """
    warnings: list[str] = []
    parsed = parse_fields(supervisor_output.fields)

    if parsed.invalid:
        warnings.append(f"Fields không hợp lệ (bỏ qua): {parsed.invalid}")

    strategy = decide_join_strategy(parsed)
    alias_map = {t: a for t, a in TABLE_ALIASES.items()}

    # ── Trường hợp có nhiều bảng phụ → query riêng ──
    if strategy.get("__multi_child__") == "separate":
        # Query chính: chỉ bảng thu_tuc
        tt_alias = alias_map["thu_tuc"]
        tt_cols = sorted(parsed.by_table.get("thu_tuc", {"ma_thu_tuc", "ten_thu_tuc"}))
        select_sql = "SELECT\n" + ",\n".join(f"    {tt_alias}.{c}" for c in tt_cols)
        from_sql = f"FROM rag.thu_tuc {tt_alias}"
        where_sql, main_params = build_where_clause(supervisor_output.procedures, tt_alias)

        main_sql = "\n".join(filter(None, [select_sql, from_sql, where_sql])) + ";"

        # Query riêng cho từng bảng phụ
        child_sqls: dict[str, str] = {}
        for table in CHILD_TABLES:
            if table in parsed.by_table:
                child_sql, _ = build_child_query(
                    table,
                    parsed.by_table[table],
                    alias_map,
                    supervisor_output.procedures,
                )
                child_sqls[table] = child_sql

        tables_used = ["thu_tuc"] + [t for t in CHILD_TABLES if t in parsed.by_table]
        fields_used = {t: sorted(c) for t, c in parsed.by_table.items()}

        return QueryPlan(
            main_sql=main_sql,
            child_sqls=child_sqls,
            tables_used=tables_used,
            fields_used=fields_used,
            warnings=warnings,
        )

    # ── Trường hợp đơn giản: 1 JOIN hoặc chỉ thu_tuc ──
    join_tables = ["thu_tuc"] + [
        t for t in CHILD_TABLES
        if t in parsed.by_table and t in strategy
    ]

    select_sql = build_select_clause(parsed, join_tables, alias_map)
    from_sql = f"FROM rag.thu_tuc {alias_map['thu_tuc']}"
    join_sql = build_join_clause(join_tables, alias_map)
    where_sql, _ = build_where_clause(
        supervisor_output.procedures, alias_map["thu_tuc"]
    )

    main_sql = "\n".join(filter(None, [
        select_sql, from_sql, join_sql, where_sql
    ])) + ";"

    fields_used = {t: sorted(c) for t, c in parsed.by_table.items()}

    return QueryPlan(
        main_sql=main_sql,
        child_sqls={},
        tables_used=join_tables,
        fields_used=fields_used,
        warnings=warnings,
    )


# ─────────────────────────────────────────────
# Helper — hiển thị kết quả
# ─────────────────────────────────────────────

def format_plan(plan: QueryPlan) -> str:
    lines = []
    lines.append("═" * 60)
    lines.append("📋 QUERY PLAN")
    lines.append("═" * 60)
    lines.append(f"Bảng sử dụng : {', '.join(plan.tables_used)}")
    lines.append("Fields theo bảng:")
    for tbl, cols in plan.fields_used.items():
        lines.append(f"  {tbl}: {', '.join(cols)}")
    if plan.warnings:
        lines.append("⚠️  Cảnh báo:")
        for w in plan.warnings:
            lines.append(f"  - {w}")
    lines.append("")
    lines.append("── MAIN SQL ──")
    lines.append(plan.main_sql)
    if plan.child_sqls:
        for tbl, sql in plan.child_sqls.items():
            lines.append(f"\n── CHILD SQL: {tbl} ──")
            lines.append(sql)
    lines.append("═" * 60)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────

if __name__ == "__main__":

    test_cases = [
        # 1. Chỉ hỏi hồ sơ
        SupervisorOutput(
            procedures=["Cấp lại thẻ căn cước"],
            fields=[
                "thanh_phan_ho_so.loai_giay_to",
                "thanh_phan_ho_so.truong_hop",
                "thanh_phan_ho_so.so_luong",
                "thanh_phan_ho_so.mau_don_to_khai",
            ],
            pipeline=["qa"],
        ),

        # 2. Hỏi phí + thời gian
        SupervisorOutput(
            procedures=["Đăng ký thành lập hộ kinh doanh"],
            fields=[
                "cach_thuc_thuc_hien.phi_le_phi",
                "cach_thuc_thuc_hien.thoi_han_giai_quyet",
                "cach_thuc_thuc_hien.hinh_thuc_nop",
                "thu_tuc.trinh_tu_thuc_hien",
            ],
            pipeline=["qa"],
        ),

        # 3. Nhiều bảng phụ — tách query riêng
        SupervisorOutput(
            procedures=["Đăng ký thành lập hộ kinh doanh"],
            fields=[
                "thu_tuc.mo_ta",
                "thu_tuc.doi_tuong_thuc_hien",
                "thu_tuc.yeu_cau_dieu_kien",
                "thanh_phan_ho_so.loai_giay_to",
                "thanh_phan_ho_so.truong_hop",
                "cach_thuc_thuc_hien.phi_le_phi",
                "cach_thuc_thuc_hien.thoi_han_giai_quyet",
                "can_cu_phap_ly.so_ky_hieu",
                "can_cu_phap_ly.trich_yeu",
            ],
            pipeline=["qa"],
        ),

        # 4. So sánh 2 thủ tục
        SupervisorOutput(
            procedures=[
                "Đăng ký thành lập hộ kinh doanh",
                "Đăng ký thành lập doanh nghiệp tư nhân",
            ],
            fields=[
                "thu_tuc.mo_ta",
                "thu_tuc.doi_tuong_thuc_hien",
                "thu_tuc.yeu_cau_dieu_kien",
                "cach_thuc_thuc_hien.phi_le_phi",
                "cach_thuc_thuc_hien.thoi_han_giai_quyet",
            ],
            pipeline=["qa"],
        ),

        # 5. Chỉ đường
        SupervisorOutput(
            procedures=["Đăng ký thành lập hộ kinh doanh"],
            fields=[
                "thu_tuc.co_quan_thuc_hien",
                "thu_tuc.dia_chi_tiep_nhan_hs",
                "thu_tuc.co_quan_co_tham_quyen",
            ],
            pipeline=["qa", "location"],
        ),

        # 6. Không liên quan — procedures rỗng
        SupervisorOutput(
            procedures=[],
            fields=[],
            pipeline=["qa"],
        ),
    ]

    labels = [
        "1. Hỏi hồ sơ cần nộp",
        "2. Hỏi phí + thời gian xử lý",
        "3. Đầy đủ 3 bảng phụ (tách riêng)",
        "4. So sánh 2 thủ tục",
        "5. Chỉ đường",
        "6. Câu hỏi không liên quan",
    ]

    for label, case in zip(labels, test_cases):
        print(f"\n{'━'*60}")
        print(f"TEST CASE: {label}")
        print(f"{'━'*60}")
        plan = build_query_plan(case)
        print(format_plan(plan))