CONFIDENCE_THRESHOLD = 0.65

VALID_DOMAINS = {
    "co_con_nho",
    "hoc_tap",
    "viec_lam",
    "cu_tru_va_giay_to_tuy_than",
    "hon_nhan_va_gia_dinh",
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
    "hon_nhan_va_gia_dinh"               : "Hôn nhân và gia đình",
    "dien_luc_nha_dat"       : "Điện lực, nhà ở, đất đai",
    "suc_khoe"               : "Sức khỏe và y tế",
    "phuong_tien"            : "Phương tiện và người lái",
    "huu_tri"                : "Hưu trí",
    "nguoi_than_qua_doi"     : "Người thân qua đời",
    "giai_quyet_khieu_kien"  : "Giải quyết khiếu kiện",
}

NO_PROCEDURE_ANSWERS = [
    "Tôi đã xác định được lĩnh vực liên quan đến câu hỏi của bạn, nhưng hiện chưa tìm thấy thủ tục hành chính phù hợp.",
    
    "Xin lỗi, tôi chưa tìm thấy thủ tục hành chính nào khớp với nội dung bạn đang hỏi. Bạn có thể cung cấp thêm thông tin chi tiết hơn không?",
    
    "Tôi đã nhận diện được lĩnh vực của câu hỏi, tuy nhiên chưa tra cứu được thủ tục tương ứng trong cơ sở dữ liệu hiện tại.",
    
    "Hiện tại tôi chưa tìm thấy thủ tục phù hợp với yêu cầu của bạn. Vui lòng mô tả rõ hơn đối tượng, cơ quan hoặc nội dung cần thực hiện.",
    
    "Tôi chưa tìm thấy thủ tục hành chính liên quan trong hệ thống. Có thể câu hỏi của bạn đang đề cập đến một trường hợp đặc thù hoặc cần thêm thông tin để tra cứu chính xác.",
    
    "Tôi đã xác định được nhóm thủ tục liên quan nhưng chưa tìm thấy thủ tục cụ thể phù hợp với yêu cầu của bạn.",
    
    "Rất tiếc, hiện chưa có kết quả thủ tục hành chính phù hợp với nội dung bạn cung cấp.",
    
]