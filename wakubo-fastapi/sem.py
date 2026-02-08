# --------- INSTALL (run once) ----------
# pip install qdrant-client torch pillow clip-anytorch

# --------- IMPORTS ----------
import uuid
import torch
import clip
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

# --------- CONFIG ----------
QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "fashion_products"
IMAGE_WEIGHT = 0.6
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# --------- INIT QDRANT ----------
client = QdrantClient(url=QDRANT_URL)

client.recreate_collection(
    collection_name=COLLECTION_NAME,
    vectors={
        "image": VectorParams(size=512, distance=Distance.COSINE),
        "text": VectorParams(size=512, distance=Distance.COSINE),
        "fused": VectorParams(size=512, distance=Distance.COSINE),
    }
)

# --------- LOAD CLIP ----------
model, preprocess = clip.load("ViT-B/32", device=DEVICE)

# --------- INGEST FUNCTION ----------
def ingest_to_qdrant(image_paths, metadata_list):
    points = []

    for img_path, meta in zip(image_paths, metadata_list):
        # Image embedding
        image = preprocess(Image.open(img_path).convert("RGB")).unsqueeze(0).to(DEVICE)
        with torch.no_grad():
            img_emb = model.encode_image(image)
            img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)

        # Text embedding
        text = meta.get("description", "")
        text_tokens = clip.tokenize([text]).to(DEVICE)
        with torch.no_grad():
            txt_emb = model.encode_text(text_tokens)
            txt_emb = txt_emb / txt_emb.norm(dim=-1, keepdim=True)

        # Fused embedding
        fused_emb = IMAGE_WEIGHT * img_emb + (1 - IMAGE_WEIGHT) * txt_emb
        fused_emb = fused_emb / fused_emb.norm(dim=-1, keepdim=True)

        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vectors={
                    "image": img_emb.cpu().numpy().flatten().tolist(),
                    "text": txt_emb.cpu().numpy().flatten().tolist(),
                    "fused": fused_emb.cpu().numpy().flatten().tolist(),
                },
                payload={
                    **meta,
                    "image_path": img_path
                }
            )
        )

    client.upsert(collection_name=COLLECTION_NAME, points=points)

# --------- USAGE ----------
# image_paths = ["images/shirt1.jpg", "images/dress1.jpg"]
# metadata_list = [
#     {"product_id": "SKU1", "description": "Black formal shirt for men", "category": "shirt", "gender": "men", "color": "black"},
#     {"product_id": "SKU2", "description": "Red summer dress for women", "category": "dress", "gender": "women", "color": "red"}
# ]
# ingest_to_qdrant(image_paths, metadata_list)