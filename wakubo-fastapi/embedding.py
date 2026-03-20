import io
from contextlib import nullcontext

import clip
import requests
import torch
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

# Global CLIP model (lazy load)
_clip_model = None
_clip_preprocess = None
_device = None

_EMBEDDING_DIM = 512
_ZERO_VECTOR = [0.0] * _EMBEDDING_DIM
_http_session = requests.Session()


def get_clip_model():
    """Lazy load CLIP model once."""
    global _clip_model, _clip_preprocess, _device
    if _clip_model is None:
        _device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading CLIP model on {_device}...")
        _clip_model, _clip_preprocess = clip.load("ViT-B/32", device=_device)
        _clip_model.eval()
        if _device == "cuda":
            torch.backends.cudnn.benchmark = True
        print("CLIP model loaded")
    return _clip_model, _clip_preprocess, _device


def _autocast_ctx(device: str):
    return torch.autocast(device_type="cuda", dtype=torch.float16) if device == "cuda" else nullcontext()


def _normalize_tensor(emb: torch.Tensor) -> torch.Tensor:
    return emb / emb.norm(dim=-1, keepdim=True).clamp_min(1e-12)


def _tensor_to_vector(emb: torch.Tensor) -> list:
    return emb[0].detach().cpu().to(torch.float32).tolist()


def _fuse_vectors(image_vector: list, text_vector: list, image_weight: float) -> list:
    fused = [image_weight * i + (1 - image_weight) * t for i, t in zip(image_vector, text_vector)]
    norm = sum(v * v for v in fused) ** 0.5
    if norm <= 1e-12:
        return _ZERO_VECTOR.copy()
    return [v / norm for v in fused]


def download_image(image_url: str, timeout: int = 10) -> Image.Image:
    """Download image from URL and return PIL image (no disk storage)."""
    response = _http_session.get(image_url, timeout=timeout)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def encode_text_embedding(text: str) -> list:
    """Encode text into a normalized CLIP embedding."""
    model, _, device = get_clip_model()
    text_tokens = clip.tokenize([text or ""], truncate=True).to(device, non_blocking=(device == "cuda"))

    with torch.inference_mode():
        with _autocast_ctx(device):
            txt_emb = model.encode_text(text_tokens)
            txt_emb = _normalize_tensor(txt_emb)

    return _tensor_to_vector(txt_emb)


def encode_image_embedding(image: Image.Image) -> list:
    """Encode image into a normalized CLIP embedding."""
    model, preprocess, device = get_clip_model()
    image_tensor = preprocess(image).unsqueeze(0).to(device, non_blocking=(device == "cuda"))

    with torch.inference_mode():
        with _autocast_ctx(device):
            img_emb = model.encode_image(image_tensor)
            img_emb = _normalize_tensor(img_emb)

    return _tensor_to_vector(img_emb)


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
    embeddings = {
        "image": None,
        "text": None,
        "fused": None,
    }

    image_vector = None
    if image_url and image_url.strip():
        try:
            image = download_image(image_url)
            image_vector = encode_image_embedding(image)
            embeddings["image"] = image_vector
        except Exception as e:
            print(f"Failed to embed image {image_url}: {e}")
            embeddings["image"] = _ZERO_VECTOR.copy()
    else:
        embeddings["image"] = _ZERO_VECTOR.copy()

    text_vector = encode_text_embedding(text)
    embeddings["text"] = text_vector

    if image_vector is not None:
        embeddings["fused"] = _fuse_vectors(image_vector, text_vector, image_weight)
    else:
        embeddings["fused"] = text_vector

    return embeddings


def init_qdrant_collection(client: QdrantClient, collection_name: str):
    """Initialize Qdrant collection with 3 vector types."""
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
            },
        )
        print(f"Qdrant collection '{collection_name}' created")
    else:
        print(f"Qdrant collection '{collection_name}' already exists")


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
    image_weight: float = 0.6,
):
    """Embed product and upsert to Qdrant using numeric ID."""
    text = f"{title} {description}".strip()
    embeddings = generate_embeddings(image_url, text, image_weight)

    numeric_id = int(shopify_gid.split("/")[-1])

    client.upsert(
        collection_name=collection_name,
        wait=False,
        points=[
            {
                "id": numeric_id,
                "vector": {
                    "image": embeddings["image"],
                    "text": embeddings["text"],
                    "fused": embeddings["fused"],
                },
                "payload": {
                    "shop": shop,
                    "shopify_gid": shopify_gid,
                    "title": title,
                    "handle": handle,
                    "description": description,
                    "product_url": product_url,
                },
            }
        ],
    )
