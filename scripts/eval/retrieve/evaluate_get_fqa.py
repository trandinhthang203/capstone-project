import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import os
import time
from app.helpers.utils.common import read_yaml


class Evaluation:
    def __init__(self):
        self.config = read_yaml()

    def make_driver(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        prefs = {
            "download.default_directory": self.config.evaluation_collect.DOWNLOAD_DIR,
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True
        }
        options.add_experimental_option("prefs", prefs)
        os.makedirs(self.config.evaluation_collect.DOWNLOAD_DIR, exist_ok=True)

        s = Service(self.config.crawl_dvc.driver_path)
        return webdriver.Chrome(service=s, options=options)

    def get_links(self, base_url: str, file_name: str, max_page: int = 15):
        driver = self.make_driver()
        wait = WebDriverWait(driver, 15)

        all_links = []
        seen = set()

        def extract_links_current_page():
            ul = wait.until(EC.presence_of_element_located((By.ID, "ulTemplate")))
            items = ul.find_elements(By.TAG_NAME, "li")
            page_links = []
            for item in items:
                try:
                    a_tag = item.find_element(By.TAG_NAME, "a")
                    link = a_tag.get_attribute("href")
                    if link and link not in seen:
                        seen.add(link)
                        page_links.append(link)
                except Exception:
                    continue
            return page_links

        try:
            driver.get(base_url)
            page_1_links = extract_links_current_page()
            all_links.extend(page_1_links)
            print(f"Trang 1: lấy được {len(page_1_links)} links")

            page_num = 2
            while page_num <= max_page:
                try:
                    old_first_link = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#ulTemplate li a"))
                    )
                    page_btn = wait.until(
                        EC.element_to_be_clickable((
                            By.XPATH,
                            f"//a[normalize-space()='{page_num}'] | "
                            f"//button[normalize-space()='{page_num}'] | "
                            f"//*[self::a or self::button or self::span][normalize-space()='{page_num}']"
                        ))
                    )
                    driver.execute_script("arguments[0].click();", page_btn)
                    wait.until(EC.staleness_of(old_first_link))
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#ulTemplate li a")))

                    page_links = extract_links_current_page()
                    all_links.extend(page_links)
                    print(f"Trang {page_num}: lấy được {len(page_links)} links")
                    page_num += 1

                except TimeoutException:
                    print(f"Không tìm được trang {page_num}, dừng lại.")
                    break
            df = pd.DataFrame(all_links)
            df.to_csv(file_name, index=False, header=False)
            print(f"Đã xong, tổng số links lấy được: {len(all_links)}")

        finally:
            driver.quit()

    def _parse_single_link(self, driver, wait, link: str, retries: int = 3) -> list:
        for attempt in range(1, retries + 1):
            try:
                driver.get(link)

                cau_hoi = wait.until(
                    EC.presence_of_element_located((By.CLASS_NAME, "main-title-sub"))
                ).text

                article = wait.until(
                    EC.presence_of_element_located((By.CLASS_NAME, "article"))
                )
                paragraphs = article.find_elements(By.TAG_NAME, "p")
                tra_loi = "\n".join(
                    p.text for p in paragraphs if p.text.strip() and "Trả lời" not in p.text
                ).strip()

                try:
                    ul = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "list-document")))
                    items = ul.find_elements(By.TAG_NAME, "li")
                    procedures = []
                    for item in items:
                        try:
                            a_tag = item.find_element(By.TAG_NAME, "a")
                            procedures.append(a_tag.text)
                        except Exception:
                            continue
                except TimeoutException:
                    procedures = []

                return [cau_hoi, tra_loi, ", ".join(procedures)]

            except WebDriverException as e:
                print(f"[Attempt {attempt}/{retries}] WebDriverException - link: {link} | {e.msg or e}")
                if attempt < retries:
                    time.sleep(2 * attempt) 
                else:
                    return [link, "ERROR", "ERROR"]

            except Exception as e:
                print(f"[Attempt {attempt}/{retries}] Lỗi link: {link} | {e}")
                if attempt < retries:
                    time.sleep(2)
                else:
                    return [link, "ERROR", "ERROR"]

    def parse_listing(self, links: list[str], batch_size: int = 10):
        columns = ["Câu hỏi", "Trả lời", "Thủ tục liên quan"]
        data = []
        driver = None
        wait = None
        total = len(links)

        try:
            for i, link in enumerate(links):
                if i % batch_size == 0:
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass
                    print(f"\n--- Khởi động driver mới (batch {i // batch_size + 1}) ---")
                    driver = self.make_driver()
                    wait = WebDriverWait(driver, 15)

                print(f"[{i + 1}/{total}] Đang xử lý: {link}")
                result = self._parse_single_link(driver, wait, link)
                data.append(result)

                if (i + 1) % batch_size == 0 or (i + 1) == total:
                    df = pd.DataFrame(data, columns=columns)
                    df.to_csv(
                        self.config.evaluation_collect.data_eval,
                        index=False,
                        encoding="utf-8-sig"
                    )
                    print(f">>> Checkpoint: đã lưu {len(data)} records")

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        print(f"\nHoàn thành! Tổng: {len(data)} records.")
        return pd.DataFrame(data, columns=columns)


if __name__ == "__main__":
    eval = Evaluation()
    eval.get_links(
        eval.config.evaluation_collect.base_url,
        eval.config.evaluation_collect.file_name,
        max_page=5
    )
    df = pd.read_csv(eval.config.evaluation_collect.file_name, header=None)
    eval.parse_listing(df[0].to_list())
