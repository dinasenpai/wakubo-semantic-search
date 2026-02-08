import io
import torch
import clip
import requests
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

# Global CLIP model (lazy load)
_clip_model = None
_clip_preprocess = None
_device = None

def get_clip_model():
    """Lazy load CLIP model once"""
    global _clip_model, _clip_preprocess, _device
    if _clip_model is None:
        _device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading CLIP model on {_device}...")
        _clip_model, _clip_preprocess = clip.load("ViT-B/32", device=_device)
        print("✅ CLIP model loaded")
    return _clip_model, _clip_preprocess, _device

def download_image(image_url: str, timeout: int = 10) -> Image.Image:
    """Download image from URL and return PIL Image (no disk storage)"""
    response = requests.get(image_url, timeout=timeout, stream=True)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGB")

def generate_embeddings(image_url: str, text: str, image_weight: float = 0.6):
    """
    Generate image, text, and fused embeddings using CLIP.
    
    Args:
        image_url: Product image URL
        text: Product description (title + description)
        image_weight: Weight for image in fused embedding (0.6 = 60% image, 40% text)
    
    Returns:
        dict with 'image', 'text', 'fused' embeddings as lists
    """
    model, preprocess, device = get_clip_model()
    
    embeddings = {
        "image": None,
        "text": None,
        "fused": None
    }
    
    # Generate image embedding
    img_emb = None
    if image_url and image_url.strip():
        try:
            image = download_image(image_url)
            image_tensor = preprocess(image).unsqueeze(0).to(device)
            
            with torch.no_grad():
                img_emb = model.encode_image(image_tensor)
                img_emb = img_emb / img_emb.norm(dim=-1, keepdim=True)
                embeddings["image"] = img_emb.cpu().numpy().flatten().tolist()
        except Exception as e:
            print(f"⚠️ Failed to embed image {image_url}: {e}")
            # Use zero vector as fallback
            embeddings["image"] = [0.0] * 512
    else:
        # No image URL, use zero vector
        embeddings["image"] = [0.0] * 512
    
    # Generate text embedding
    text_tokens = clip.tokenize([text], truncate=True).to(device)
    with torch.no_grad():
        txt_emb = model.encode_text(text_tokens)
        txt_emb = txt_emb / txt_emb.norm(dim=-1, keepdim=True)
        embeddings["text"] = txt_emb.cpu().numpy().flatten().tolist()
    
    # Generate fused embedding
    if img_emb is not None:
        fused_emb = image_weight * img_emb + (1 - image_weight) * txt_emb
        fused_emb = fused_emb / fused_emb.norm(dim=-1, keepdim=True)
        embeddings["fused"] = fused_emb.cpu().numpy().flatten().tolist()
    else:
        # No image, fused = text only
        embeddings["fused"] = embeddings["text"]
    
    return embeddings

def init_qdrant_collection(client: QdrantClient, collection_name: str):
    """Initialize Qdrant collection with 3 vector types"""
    collections = client.get_collections().collections
    exists = any(col.name == collection_name for col in collections)
    
    if not exists:
        print(f"Creating Qdrant collection: {collection_name}")
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "image": VectorParams(size=512, distance=Distance.COSINE),
                "text": VectorParams(size=512, distance=Distance.COSINE),
                "fused": VectorParams(size=512, distance=Distance.COSINE),
            }
        )
        print(f"✅ Qdrant collection '{collection_name}' created")
    else:
        print(f"✅ Qdrant collection '{collection_name}' already exists")

def upsert_product_to_qdrant(
    client: QdrantClient,
    collection_name: str,
    shopify_gid: str,
    shop: str,
    title: str,
    description: str,
    handle: str,
    image_url: str,
    product_url: str,
    image_weight: float = 0.6
):
    """
    Embed product and upsert to Qdrant using numeric ID.
    """
    # Combine title + description for text embedding
    text = f"{title} {description}".strip()
    
    # Generate embeddings
    embeddings = generate_embeddings(image_url, text, image_weight)
    
    # Extract numeric ID from shopify_gid (e.g., "gid://shopify/Product/123" -> 123)
    numeric_id = int(shopify_gid.split("/")[-1])
    
    # Upsert to Qdrant with numeric ID
    client.upsert(
        collection_name=collection_name,
        points=[
            {
                "id": numeric_id,  # Use numeric ID instead of full gid
                "vector": {
                    "image": embeddings["image"],
                    "text": embeddings["text"],
                    "fused": embeddings["fused"],
                },
                "payload": {
                    "shop": shop,
                    "shopify_gid": shopify_gid,  # Store full gid in payload for PostgreSQL lookup
                    "title": title,
                    "handle": handle,
                    "product_url": product_url,
                }
            }
        ]
    )

