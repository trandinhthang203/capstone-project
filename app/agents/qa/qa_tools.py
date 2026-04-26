from __future__ import annotations
from dataclasses import dataclass, field
from app.db.session import get_db
from app.agents.base.utils import format_context


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
PROCEDURE_MATCH_COLUMN = "ma_thu_tuc"

# Luôn SELECT ma_thu_tuc để có thể liên kết kết quả
ALWAYS_SELECT = {"thu_tuc": {"ma_thu_tuc", "ten_thu_tuc", "link_tham_khao"}}


# ─────────────────────────────────────────────
# Kiểu dữ liệu
# ─────────────────────────────────────────────

@dataclass
class SupervisorOutput:
    procedures: list[str]
    fields: list[str]         

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
    if len(child_tables_needed) >= 4:
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
) -> tuple[str, dict]:
    if not procedures:
        return "", {}

    where_sql = f"WHERE {main_alias}.{PROCEDURE_MATCH_COLUMN} = ANY(:procedures)"
    params = {"procedures": procedures}
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
    param_offset: int = 1,   # giữ signature, không còn dùng
) -> tuple[str, dict]:
    alias = alias_map[table]

    cols_to_select = sorted(columns | {"ma_thu_tuc"})
    select_parts = [f"    {alias}.{c}" for c in cols_to_select]
    select_sql = "SELECT\n" + ",\n".join(select_parts)

    from_sql = f"FROM rag.{table} {alias}"
    where_sql = ""
    params: dict = {}

    if procedures:
        where_sql = f"WHERE {alias}.ma_thu_tuc = ANY(:procedures)"
        params = {"procedures": procedures}

    sql = "\n".join(filter(None, [select_sql, from_sql, where_sql])) + ";"
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

if __name__ == "__main__":
    case = SupervisorOutput(
        procedures=["1.000466", "1.000757"],
        fields=[
            # bảng chính
            "thu_tuc.ten_thu_tuc"
            "thu_tuc.linh_vuc",
            "thu_tuc.cap_thuc_hien",
            "thu_tuc.co_quan_thuc_hien",
            # bảng phụ — sẽ trigger separate queries
            "thanh_phan_ho_so.loai_giay_to",
            "thanh_phan_ho_so.so_luong",
            "thanh_phan_ho_so.mau_don_to_khai",
            "cach_thuc_thuc_hien.hinh_thuc_nop",
            "cach_thuc_thuc_hien.thoi_han_giai_quyet",
            # "can_cu_phap_ly.so_ky_hieu",
            # "can_cu_phap_ly.trich_yeu",
            # field không hợp lệ — để test warning
            # "thu_tuc.cot_khong_ton_tai",
            # "bang_la.cot_gi_do",
        ],
    )

    from sqlalchemy import text
    
    plan = build_query_plan(case)
    # Lấy params riêng
    _, main_params = build_where_clause(case.procedures, TABLE_ALIASES["thu_tuc"])
    
    print(plan.main_sql)
    
    with next(get_db()) as db:
        # ── MAIN QUERY ──
        result = db.execute(text(plan.main_sql), main_params)
        columns = list(result.keys())   # ← lấy tên cột từ đây
        rows = result.fetchall()
        print(format_context(rows, columns))

        # # ── CHILD QUERIES ──
        # for tbl, sql in plan.child_sqls.items():
        #     _, child_params = build_where_clause(case.procedures, TABLE_ALIASES[tbl])
        #     child_result = db.execute(text(sql), child_params)
        #     child_columns = list(child_result.keys())
        #     child_rows = child_result.fetchall()
        #     print(f"\n{tbl}:")
        #     print(format_context(child_rows, child_columns))