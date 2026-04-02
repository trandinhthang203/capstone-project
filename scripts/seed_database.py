from app.db.session import get_db
from sqlalchemy.orm import Session
from scripts.models.procedure import Thu_Tuc
from scripts.models.component import Thanh_Phan_Ho_So
from scripts.models.basis import Can_Cu_Phap_Ly
from scripts.models.method import Cach_Thuc_Thuc_Hien
import os
from scripts.utils.common import read_yaml, read_json


class Seed_Database:
    def __init__(self, db: Session):
        self.db = db
        self.config = read_yaml()

    def _build_procedures(self, procedure: dict) -> Thu_Tuc:
        return Thu_Tuc(
            ma_thu_tuc=procedure["Mã thủ tục:"],
            link_tham_khao=procedure["reference"],
            ten_thu_tuc=procedure["Tên thủ tục:"],
            cap_thuc_hien=procedure["Cấp thực hiện:"],
            so_quyet_dinh=procedure["Số quyết định:"],
            loai_thu_tuc=procedure["Loại thủ tục:"],
            linh_vuc=procedure["Lĩnh vực:"],
            trinh_tu_thuc_hien=procedure["Trình tự thực hiện:"],
            doi_tuong_thuc_hien=procedure["Đối tượng thực hiện:"],
            co_quan_thuc_hien=procedure["Cơ quan thực hiện:"],
            co_quan_co_tham_quyen=procedure["Cơ quan có thẩm quyền:"],
            dia_chi_tiep_nhan_hs=procedure["Địa chỉ tiếp nhận HS:"],
            co_quan_duoc_uy_quyen=procedure["Cơ quan được ủy quyền:"],
            co_quan_phoi_hop=procedure["Cơ quan phối hợp:"],
            ket_qua_thuc_hien=procedure["Kết quả thực hiện:"],
            yeu_cau_dieu_kien=procedure["Yêu cầu, điều kiện thực hiện:"],
            tu_khoa=procedure["Từ khóa:"],
            mo_ta=procedure["Mô tả:"],
        )

    def _build_methods(self, procedure: dict) -> list[Cach_Thuc_Thuc_Hien]:
        ma = procedure["Mã thủ tục:"]
        return [
            Cach_Thuc_Thuc_Hien(
                hinh_thuc_nop=m["Hình thức nộp"],
                thoi_han_giai_quyet=m["Thời hạn giải quyết"],
                phi_le_phi=m["Phí, lệ phí"],
                mo_ta=m["Mô tả"],
                ma_thu_tuc=ma,
            )
            for m in procedure["Cách thức thực hiện:"]
        ]

    def _build_components(self, procedure: dict) -> list[Thanh_Phan_Ho_So]:
        ma = procedure["Mã thủ tục:"]
        return [
            Thanh_Phan_Ho_So(
                truong_hop=key,
                loai_giay_to=c["Tên giấy tờ"],
                mau_don_to_khai=c["Mẫu đơn, tờ khai"],
                so_luong=c["Số lượng"],
                ma_thu_tuc=ma,
            )
            for key, values in procedure["Thành phần hồ sơ:"].items()
            for c in values
        ]

    def _build_basis(self, procedure: dict) -> list[Can_Cu_Phap_Ly]:
        ma = procedure["Mã thủ tục:"]
        return [
            Can_Cu_Phap_Ly(
                so_ky_hieu=b["Số ký hiệu"],
                trich_yeu=b["Trích yếu"],
                ngay_ban_hanh=b["Ngày ban hành"],
                co_quan_ban_hanh=b["Cơ quan ban hành"],
                ma_thu_tuc=ma,
            )
            for b in procedure["Căn cứ pháp lý:"]
        ]

    def import_data(self):
        base_dir = self.config.process_forms.proceduces_processed
        files = [f for f in os.listdir("data/processed") if f.endswith(".json")]

        for filename in files:
            print(filename)
            procedure = read_json(base_dir, filename)
            ma = procedure["Mã thủ tục:"]
            print(ma)

            try:
                self.db.add(self._build_procedures(procedure))
                self.db.add_all(self._build_methods(procedure))
                self.db.add_all(self._build_components(procedure))
                self.db.add_all(self._build_basis(procedure))

                self.db.commit()
                print(f"Đã thêm thủ tục: {ma}")


            except Exception as e:
                self.db.rollback()
                print(f"Lỗi khi thêm thủ tục {ma}: {e}")


if __name__ == "__main__":
    seed = Seed_Database(next(get_db()))
    seed.import_data()