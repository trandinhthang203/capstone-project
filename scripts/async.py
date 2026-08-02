import asyncio
import time

async def tai_du_lieu(ten, thoi_gian):
    print(f"Đang tải dữ liệu {ten}...")
    await asyncio.sleep(thoi_gian)
    print(f"Đã tải xong dữ liệu {ten}.")

def tai_du_lieu_sync(ten, thoi_gian):
    print(f"Đang tải dữ liệu {ten}...")
    time.sleep(thoi_gian)
    print(f"Đã tải xong dữ liệu {ten}.")

def main_sync():
    bat_dau = time.time()
    tai_du_lieu_sync("Dữ liệu A", 2)
    tai_du_lieu_sync("Dữ liệu B", 3)
    tai_du_lieu_sync("Dữ liệu C", 1)
    print(f"Tổng thời gian tải dữ liệu: {time.time() - bat_dau:.2f} giây")


async def main():
    bat_dau = time.time()
    tasks = [
        tai_du_lieu("Dữ liệu A", 2),
        tai_du_lieu("Dữ liệu B", 3),
        tai_du_lieu("Dữ liệu C", 1),
    ]
    await asyncio.gather(*tasks)
    print(f"Tổng thời gian tải dữ liệu: {time.time() - bat_dau:.2f} giây")

# asyncio.run(main())
main_sync()