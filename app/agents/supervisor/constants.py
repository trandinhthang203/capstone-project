CONFIDENCE_THRESHOLD = 0.65

VALID_DOMAINS = {
    "co_con_nho",
    "hoc_tap",
    "viec_lam",
    "cu_tru_va_giay_to_tuy_than",
    "hon_nhan",
    "dien_luc_nha_dat",
    "suc_khoe",
    "phuong_tien",
    "huu_tri",
    "nguoi_than_qua_doi",
    "giai_quyet_khieu_kien",
}

DOMAIN_LABELS: dict[str, str] = {
    "co_con_nho"             : "Có con nhỏ",
    "hoc_tap"                : "Học tập",
    "viec_lam"               : "Việc làm",
    "cu_tru_va_giay_to_tuy_than"                 : "Cư trú và giấy tờ tùy thân",
    "hon_nhan"               : "Hôn nhân và gia đình",
    "dien_luc_nha_dat"       : "Điện lực, nhà ở, đất đai",
    "suc_khoe"               : "Sức khỏe và y tế",
    "phuong_tien"            : "Phương tiện và người lái",
    "huu_tri"                : "Hưu trí",
    "nguoi_than_qua_doi"     : "Người thân qua đời",
    "giai_quyet_khieu_kien"  : "Giải quyết khiếu kiện",
}