import requests
import base64

ROBOFLOW_API_KEY = "TMlSASZ8SV6bioL6KYD3"
WORKFLOW_ID = "test-validation-set/detect-count-and-visualize-3"
IMAGE_PATH = "/Volumes/T7/Temika/Images/png/4_2_9_2_04.png"


# API URL for Roboflow local inference
url = f"http://localhost:9001/infer/workflows/{WORKFLOW_ID}"

# Read and encode your image as base64
with open(IMAGE_PATH, "rb") as image_file:
    image_base64 = base64.b64encode(image_file.read()).decode('utf-8')

# Create JSON payload with embedded base64 image
payload = {
    "api_key": ROBOFLOW_API_KEY,
    "inputs": {
        "image": {
            "type": "base64",
            "value": image_base64
        }
    }
}

# Send request as JSON payload
response = requests.post(url, json=payload)

# Check the result
if response.status_code == 200:
    predictions = response.json()
    print(predictions)
else:
    print(f"Request failed: {response.status_code}, {response.text}")


