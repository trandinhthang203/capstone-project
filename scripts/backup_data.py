import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import os
import time
from urllib.parse import urlparse, parse_qs
from app.helpers.utils.common import read_yaml
import requests



class Backup:
    def __init__(self):
        self.config = read_yaml()

    def make_driver(self, download_dir):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)
        os.makedirs(download_dir, exist_ok=True)

        s = Service(self.config.crawl_dvc.driver_path)
        return webdriver.Chrome(service=s, options=options)

    def wait_for_download(self, download_dir, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            files = [
                f for f in os.listdir(download_dir)
                if not f.endswith((".crdownload", ".tmp"))
            ]
            if files:
                full_paths = [os.path.join(download_dir, f) for f in files]
                newest = max(full_paths, key=os.path.getmtime)
                return newest
            time.sleep(0.5)

        print("Timeout chờ download")
        return None


    def parse_listing(self, links: list[str], field: str):
        download_dir = os.path.join(self.config.backup_data.DOWNLOAD_DIR, field)
        driver = self.make_driver(download_dir)
        records = []

        for link in links:
            try:
                driver.get(link)
                wait = WebDriverWait(driver, 10)

                a_tag = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "url")))
                reference = a_tag.get_attribute("href")
                driver.get(reference)

                wait = WebDriverWait(driver, 10)
                attributes = wait.until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".info-row"))
                )

                ma_thu_tuc = None
                for attribute in attributes:
                    try:
                        key = attribute.find_element(
                            By.CSS_SELECTOR, ".col-sm-3.col-xs-12.key"
                        ).get_attribute("textContent").strip()

                        if key == "Mã thủ tục:":
                            value_el = attribute.find_element(By.CSS_SELECTOR, ".col-sm-9")
                            ma_thu_tuc = value_el.get_attribute("textContent").strip()

                    except Exception as e:
                        print("Lỗi đọc info-row:", e)

                downloaded_path = None
                try:
                    download_anchor = wait.until(
                        EC.presence_of_element_located((
                            By.CSS_SELECTOR,
                            'a[title="Tải xuống chi tiết thủ tục"]'
                        ))
                    )
                    href = download_anchor.get_attribute("href")
                    print(f"Found anchor: {href}")

                    cookies = {c['name']: c['value'] for c in driver.get_cookies()}
                    headers = {"User-Agent": driver.execute_script("return navigator.userAgent;")}

                    response = requests.get(href, cookies=cookies, headers=headers, stream=True)
                    if response.status_code == 200:
                        content_disposition = response.headers.get("Content-Disposition", "")
                        if "filename=" in content_disposition:
                            filename = content_disposition.split("filename=")[-1].strip().strip('"')
                        else:
                            ma_tthc = href.split("maTTHC=")[-1].split("&")[0]
                            filename = f"{ma_tthc}.docx"

                        file_path = os.path.join(download_dir, filename)
                        with open(file_path, "wb") as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)

                        downloaded_path = file_path
                        print(f"Downloaded: {downloaded_path}")
                    else:
                        print(f"Lỗi HTTP: {response.status_code}")

                except Exception as e:
                    print(f"Lỗi download: {e}")

                records.append({
                    "Mã thủ tục": ma_thu_tuc,
                    "Đường dẫn": reference,
                    "File": downloaded_path,
                })
                print(f">>> Checkpoint: {ma_thu_tuc} | {downloaded_path}")

            except Exception as e:
                print(f"Lỗi xử lý link {link}: {e}")

        driver.quit()

        df = pd.DataFrame(records)
        output_path = os.path.join(self.config.backup_data.DOWNLOAD_DIR, f"{field}.csv")
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f">>> Đã lưu {len(records)} records vào {output_path}")
        return df


if __name__ == "__main__":
    eval = Backup()

    for field in os.listdir(eval.config.backup_data.DOWNLOAD_DIR):
        full_path = os.path.join(eval.config.backup_data.DOWNLOAD_DIR, field)
        if not os.path.isdir(full_path):  
            continue
        csv_path = os.path.join(eval.config.backup_data.data_links, f"{field}.csv")
        df = pd.read_csv(csv_path, header=None)
        eval.parse_listing(df[0].to_list(), field)

