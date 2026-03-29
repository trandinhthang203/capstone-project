import boto3
import os
import json
from scripts.utils.common import read_yaml, read_json
from dotenv import load_dotenv
load_dotenv()

BUCKET = os.getenv("AWS_BUCKET")
REGION = os.getenv("AWS_DEFAULT_REGION")

class ProcessForms:
    def __init__(self):
        self.config = read_yaml()

        self.s3 = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_DEFAULT_REGION')
        )

    def gen_url_file(self, filepath: str) -> str:
        file_name = os.path.basename(filepath).replace(" ", "")
        self.s3.upload_file(filepath, BUCKET, file_name.strip(), ExtraArgs={
            'ContentType': 'application/pdf'
        })

        url = f"https://{BUCKET}.s3.{REGION}.amazonaws.com/{file_name}"
        print("Upload thành công:", url)
        return url

    def convert_url(self):
        raw_dir = self.config.process_forms.proceduces_raw
        for json_file in os.listdir(raw_dir):
            if not json_file.endswith(".json"):
                continue

            procedure = read_json(raw_dir, json_file)

            for value in procedure["Thành phần hồ sơ:"].values():
                for component in value:
                    raw = component["Mẫu đơn, tờ khai"]
                    if not raw:
                        continue

                    paths = [p.strip() for p in raw.split(",") if p.strip()]
                    urls = [self.gen_url_file(p) for p in paths]
                    component["Mẫu đơn, tờ khai"] = ", ".join(urls)

            output_path = os.path.join(self.config.process_forms.proceduces_processed, json_file)
            print(output_path)
            with open(output_path, "w", encoding="utf-8") as file:
                json.dump(procedure, file, indent=4, ensure_ascii=False)
    
if __name__ == "__main__":
    form = ProcessForms()
    form.convert_url()
