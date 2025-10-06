import requests
import base64
import json
import pandas as pd  
import ast  # <-- allows safe parsing of Python dict strings

ROBOFLOW_API_KEY = "TMlSASZ8SV6bioL6KYD3"
WORKFLOW_ID = "test-validation-set/detect-count-and-visualize-3"
IMAGE_PATH = "/Volumes/T7/Temika/Images/png/4_2_9_2_04.png"


url = f"http://localhost:9001/infer/workflows/{WORKFLOW_ID}"

# Read and encode image
with open(IMAGE_PATH, "rb") as image_file:
    image_base64 = base64.b64encode(image_file.read()).decode('utf-8')

payload = {
    "api_key": ROBOFLOW_API_KEY,
    "inputs": {
        "image": {
            "type": "base64",
            "value": image_base64
        }
    }
}

response = requests.post(url, json=payload)

if response.status_code == 200:
    data = json.loads(response.text)
    outputs = data.get("outputs", [])

    if outputs:
        output = outputs[0]

        predictions = output.get("predictions", [])


        objects = []

        for pred in predictions:
            # Skip empty or malformed entries
            if not pred or not isinstance(pred, str):
                continue

            # Only parse entries that look like dictionaries
            pred_str = pred.strip()
            if pred_str.startswith("{") and pred_str.endswith("}"):
                try:
                    pred_dict = ast.literal_eval(pred_str)
                except Exception:
                    continue  # Skip if still malformed

                obj_record = {
                    "detection_id": pred_dict.get("detection_id"),
                    "class": pred_dict.get("class"),
                    "class_id": pred_dict.get("class_id"),
                    "confidence": pred_dict.get("confidence"),
                    "x": pred_dict.get("x"),
                    "y": pred_dict.get("y"),
                    "width": pred_dict.get("width"),
                    "height": pred_dict.get("height"),
                    "parent_id": pred_dict.get("parent_id")
                }
                objects.append(obj_record)



        # Save as DataFrame and JSON
        df_predictions = pd.DataFrame(objects)
        print(df_predictions)
        df_predictions.to_csv("predictions.csv", index=False)

        # Save annotated image
        visualization_base64 = output.get("output_image", {}).get("value")
        if visualization_base64:
            visualization_bytes = base64.b64decode(visualization_base64)
            with open("annotated_image.png", "wb") as f:
                f.write(visualization_bytes)
            print("Annotated image saved as 'annotated_image.png'")
        else:
            print("No visualization data returned.")
    else:
        print("No outputs found in response.")
else:
    print(f"Request failed: {response.status_code}, {response.text}")
