import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import os
import time
from scripts.utils.common import read_yaml
import json

class Crawl_DVC:
    def __init__(self):
        self.config = read_yaml()
    
    def make_driver(self):
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless")         
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-images")    
        options.add_argument("--blink-settings=imagesEnabled=false")

        prefs = {
            "download.default_directory": self.config.crawl_dvc.download_dir,
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True 
        }
        options.add_experimental_option("prefs", prefs)
        os.makedirs(self.config.crawl_dvc.download_dir, exist_ok=True)

        s = Service(self.config.crawl_dvc.driver_path)
        return webdriver.Chrome(service=s, options=options)
    
    def get_links(self, base_url: str, file_name: str):
        """ Lấy danh sách các liên kết thủ tục"""
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

            for page_num in [2, 3]:
                try:
                    old_first_link = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#ulTemplate li a"))
                    )

                    page_btn = wait.until(
                        EC.element_to_be_clickable(
                            (
                                By.XPATH,
                                f"//a[normalize-space()='{page_num}'] | "
                                f"//button[normalize-space()='{page_num}'] | "
                                f"//*[self::a or self::button or self::span][normalize-space()='{page_num}']"
                            )
                        )
                    )

                    driver.execute_script("arguments[0].click();", page_btn)

                    wait.until(EC.staleness_of(old_first_link))

                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#ulTemplate li a")))

                    page_links = extract_links_current_page()
                    all_links.extend(page_links)
                    print(f"Trang {page_num}: lấy được {len(page_links)} links")

                except TimeoutException:
                    print(f"Không tìm được hoặc không click được trang {page_num}")
                    break

            df = pd.DataFrame(all_links)
            df.to_csv(file_name, index=False, header=False)

            print(f"Đã xong, tổng số links lấy được: {len(all_links)}")

        finally:
            driver.quit()

    def wait_for_download(self, download_dir, filename, timeout=30):
        path = os.path.join(download_dir, filename)
        start = time.time()

        while time.time() - start < timeout:
            if os.path.exists(path):
                tmp_files = [f for f in os.listdir(download_dir) if f.endswith(('.crdownload', '.tmp'))]
                if not tmp_files:
                    pdf_path = os.path.splitext(path)[0] + ".pdf"
                    return pdf_path
            time.sleep(0.5)

        print(f"Timeout chờ download: {filename}")
        return None
    
    def parse_table(self, table, driver=None, download_col="Mẫu đơn, tờ khai"):
        headers = []
        try:
            thead = table.find_element(By.TAG_NAME, "thead")
            if thead:
                headers = [th.get_attribute("textContent").strip() for th in thead.find_elements(By.TAG_NAME, "th")]
        except:
            return []

        rows = []
        try:
            tbody = table.find_element(By.TAG_NAME, "tbody")
            if tbody:
                for tr in tbody.find_elements(By.TAG_NAME, "tr"):
                    tds = tr.find_elements(By.TAG_NAME, "td")
                    cells = []

                    for i, td in enumerate(tds):
                        col_name = headers[i] if i < len(headers) else ""

                        if col_name == download_col and driver:
                            spans = td.find_elements(By.TAG_NAME, "span")
                            file_paths = []

                            for span in spans:
                                file_name = span.get_attribute("textContent").strip()
                                if not file_name:
                                    continue

                                try:
                                    old_path = os.path.join(self.config.crawl_dvc.download_dir, file_name)
                                    if os.path.exists(old_path):
                                        os.remove(old_path)

                                    driver.execute_script("arguments[0].click();", span)

                                    downloaded_path = self.wait_for_download(self.config.crawl_dvc.download_dir, file_name)
                                    file_paths.append(downloaded_path or file_name)

                                except Exception as e:
                                    print(f"Lỗi download {file_name}:", e)
                                    file_paths.append(file_name)

                            cells.append(", ".join(file_paths))
                        else:
                            cells.append(td.get_attribute("textContent").strip())

                    if cells and len(cells) == len(headers):
                        rows.append(dict(zip(headers, cells)))
        except:
            pass

        return rows
    
    def parse_report_components(self, container, driver):
        result = {}
        col_sm9 = container.find_element(By.CSS_SELECTOR, ".col-sm-9")
        children = col_sm9.find_elements(By.XPATH, "./*")
        current_key = "Mặc định"

        for child in children:
            tag = child.tag_name
            class_attr = child.get_attribute("class") or ""

            if tag == "div" and "key" in class_attr:
                current_key = child.get_attribute("textContent").strip()
            elif tag == "table":
                rows = self.parse_table(child, driver=driver)  
                result[current_key] = rows

        return result
    
    def parse_listing(self, links: list[str]):
        driver = self.make_driver()

        for link in links:
            driver.get(link)

            a_tag = driver.find_element(By.CLASS_NAME, "url")
            driver.get(a_tag.get_attribute("href"))
            
            wait = WebDriverWait(driver, 10)

            attributes = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".info-row"))
            )
            procedure = {}
            for attribute in attributes:
                try:
                    key = attribute.find_element(By.CSS_SELECTOR, ".col-sm-3.col-xs-12.key").get_attribute("textContent").strip()
                    list_key_table = ["Cách thức thực hiện:", "Căn cứ pháp lý:"]
                    value_element = attribute.find_element(By.CSS_SELECTOR, ".col-sm-9")
                    value = value_element.get_attribute("textContent").strip()

                    if key in list_key_table:
                        procedure[key] = self.parse_table(attribute)
                    elif key == "Thành phần hồ sơ:":
                        procedure[key] = self.parse_report_components(attribute, driver)
                    else:
                        procedure[key] = value

                    if key == "Mã thủ tục:":
                        PROCEDUCES_PATH = f"{value}.json"

                except Exception as e:
                    print("Lỗi tại row:", attribute.get_attribute("outerHTML"))
                    print("Error:", e)
                
            json_path = os.path.join(self.config.crawl_dvc.proceduces_raw, PROCEDUCES_PATH)
            with open(json_path, "a", encoding="utf-8") as file:
                json.dump(procedure, file, indent=4, ensure_ascii=False)
        driver.quit()

    
if __name__ == "__main__":
    crawler = Crawl_DVC()
    # crawler.get_links(crawler.config.craw_dvc.base_url, crawler.config.craw_dvc.file_name)
    df = pd.read_csv(crawler.config.crawl_dvc.file_name, header=None)
    crawler.parse_listing(df[0].to_list())