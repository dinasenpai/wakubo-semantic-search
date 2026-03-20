import os
import hmac
import hashlib
import secrets
import time
import urllib.parse
import requests
import io

from fastapi import FastAPI, Depends, Form, HTTPException, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from PIL import Image
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from db import Base, engine, get_db
from models import ShopToken, Product
from embedding import (
    init_qdrant_collection,
    upsert_product_to_qdrant,
    encode_text_embedding,
    encode_image_embedding,
)


app = FastAPI(title="Wakubo Semantic Search Backend")

# Create tables
Base.metadata.create_all(bind=engine)

# Environment variables
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET")
SCOPES = os.getenv("SCOPES", "read_products")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://wakubo-semantic-search-production.up.railway.app")
QDRANT_URL = os.getenv("QDRANT_URL", "https://fce0ab36-2503-4245-ad43-e4c8a472089a.eu-central-1-0.aws.cloud.qdrant.io")
QDRANT_API_KEY= os.getenv("QDRANT_API_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.PFBDbr1kZ_vYHUWJ-aliCrW99qkmMHtFEyTRoIbrFOM")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "wakubo_products")
IMAGE_WEIGHT = float(os.getenv("IMAGE_WEIGHT", "0.6"))
WEBHOOK_CALLBACK_URL = f"{APP_BASE_URL.rstrip('/')}/webhooks/shopify"
PRODUCT_WEBHOOK_TOPICS = ("PRODUCTS_CREATE", "PRODUCTS_UPDATE", "PRODUCTS_DELETE")

qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
init_qdrant_collection(qdrant_client, QDRANT_COLLECTION)

# CORS - allow any Shopify store + local dev
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.myshopify\.com",
    allow_origins=["http://127.0.0.1:9293", "http://localhost:9293"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory OAuth state storage (use Redis in production)
OAUTH_STATES = {}

def verify_shop_domain(shop: str) -> bool:
    """Validate shop domain format"""
    return (
        isinstance(shop, str) 
        and shop.endswith(".myshopify.com") 
        and "/" not in shop 
        and "?" not in shop
        and len(shop) < 200
    )

def verify_hmac(query_params: dict, secret: str) -> bool:
    """Verify Shopify HMAC signature"""
    params = {k: v for k, v in query_params.items() if k != "hmac"}
    message = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, query_params.get("hmac", ""))

def get_shop_token(db: Session, shop: str) -> str:
    """Get stored access token for shop"""
    row = db.query(ShopToken).filter_by(shop=shop).first()
    if not row:
        raise HTTPException(404, f"Shop {shop} not installed. Please install the app first.")
    return row.access_token

def shopify_graphql(shop: str, access_token: str, query: str, variables: dict = None) -> dict:
    """Call Shopify Admin GraphQL API"""
    url = f"https://{shop}/admin/api/2026-01/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": access_token,
    }
    resp = requests.post(url, json={"query": query, "variables": variables or {}}, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    
    if payload.get("errors"):
        raise HTTPException(500, {"shopify_errors": payload["errors"]})
    
    return payload


def ensure_product_webhooks(shop: str, access_token: str) -> dict:
    """
    Ensure product create/update/delete webhooks exist for this app installation.
    Uses explicit GraphQL registration so webhook delivery does not depend only on CLI deploy state.
    """
    mutation = """
    mutation RegisterWebhook($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
      webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
        webhookSubscription { id topic }
        userErrors { field message }
      }
    }
    """

    created = []
    already_exists = []
    failed = []

    for topic in PRODUCT_WEBHOOK_TOPICS:
        payload = shopify_graphql(
            shop,
            access_token,
            mutation,
            {
                "topic": topic,
                "webhookSubscription": {
                    "callbackUrl": WEBHOOK_CALLBACK_URL,
                    "format": "JSON",
                },
            },
        )

        result = payload["data"]["webhookSubscriptionCreate"]
        errors = result.get("userErrors") or []
        if not errors:
            created.append(topic)
            continue

        message_text = " | ".join((e.get("message") or "").lower() for e in errors)
        if "already" in message_text and ("taken" in message_text or "exists" in message_text):
            already_exists.append(topic)
        else:
            failed.append({"topic": topic, "errors": errors})

    return {
        "callback_url": WEBHOOK_CALLBACK_URL,
        "created": created,
        "already_exists": already_exists,
        "failed": failed,
    }

# ==================== OAuth Endpoints ====================

@app.get("/auth/install")
def auth_install(shop: str):
    """Step 1: Redirect merchant to Shopify OAuth authorization"""
    if not all([SHOPIFY_API_KEY, SHOPIFY_API_SECRET, APP_BASE_URL]):
        raise HTTPException(500, "Missing SHOPIFY_API_KEY, SHOPIFY_API_SECRET, or APP_BASE_URL in .env")
    
    if not verify_shop_domain(shop):
        raise HTTPException(400, "Invalid shop domain")
    
    state = secrets.token_urlsafe(24)
    OAUTH_STATES[state] = int(time.time())
    
    redirect_uri = f"{APP_BASE_URL}/auth/callback"
    authorize_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={urllib.parse.quote(SHOPIFY_API_KEY)}"
        f"&scope={urllib.parse.quote(SCOPES)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&state={urllib.parse.quote(state)}"
        f"&grant_options[]=per-user"  # Request offline token
    )
    
    return RedirectResponse(authorize_url)

@app.get("/auth/callback")
def auth_callback(
    request: Request, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Step 2: Exchange code for access token and auto-sync products"""
    qp = dict(request.query_params)
    
    shop = qp.get("shop")
    code = qp.get("code")
    state = qp.get("state")
    
    if not all([shop, code, state]):
        raise HTTPException(400, "Missing required OAuth parameters")
    
    if not verify_shop_domain(shop):
        raise HTTPException(400, "Invalid shop domain")
    
    # Verify state (anti-CSRF)
    created = OAUTH_STATES.get(state)
    if not created or (int(time.time()) - created > 300):
        raise HTTPException(400, "Invalid or expired OAuth state")
    OAUTH_STATES.pop(state, None)
    
    # Verify HMAC
    if not verify_hmac(qp, SHOPIFY_API_SECRET):
        raise HTTPException(401, "Invalid HMAC signature")
    
    # Exchange code for access token
    token_url = f"https://{shop}/admin/oauth/access_token"
    resp = requests.post(
        token_url,
        json={
            "client_id": SHOPIFY_API_KEY,
            "client_secret": SHOPIFY_API_SECRET,
            "code": code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token_data = resp.json()
    access_token = token_data.get("access_token")
    
    if not access_token:
        raise HTTPException(500, {"error": "No access token in response", "response": token_data})
    
    # Store token in database
    shop_token = db.query(ShopToken).filter_by(shop=shop).first()
    if not shop_token:
        shop_token = ShopToken(shop=shop, access_token=access_token)
    else:
        shop_token.access_token = access_token
    
    db.add(shop_token)
    db.commit()

    # Ensure webhooks are registered for this installation.
    try:
        webhook_status = ensure_product_webhooks(shop, access_token)
        print(f"[webhook] registration status for {shop}: {webhook_status}")
    except Exception as e:
        print(f"[webhook] failed to register webhooks for {shop}: {e}")
    
    # Auto-sync products in background
    background_tasks.add_task(sync_shop_products, shop, access_token, db)
    
    return HTMLResponse(f"""
        <html>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>✅ App Installed Successfully!</h1>
                <p>Store: <strong>{shop}</strong></p>
                <p>Products are syncing in the background...</p>
                <p>You can close this tab and return to your admin.</p>
            </body>
        </html>
    """)

# ==================== Webhook Endpoint ====================

@app.post("/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle Shopify webhooks for product changes"""
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    topic = request.headers.get("X-Shopify-Topic", "")
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
    print(f"[webhook] received topic={topic} shop={shop} webhook_id={webhook_id}")
    if not SHOPIFY_API_SECRET:
        raise HTTPException(500, "Missing SHOPIFY_API_SECRET in backend environment")
    
    body = await request.body()
    
    # Verify webhook HMAC
    digest = hmac.new(
        SHOPIFY_API_SECRET.encode(),
        body,
        hashlib.sha256
    ).digest()
    computed_hmac = __import__("base64").b64encode(digest).decode()
    
    if not hmac.compare_digest(computed_hmac, hmac_header):
        print(f"[webhook] invalid hmac topic={topic} shop={shop} webhook_id={webhook_id}")
        raise HTTPException(401, "Invalid webhook signature")
    
    data = await request.json()
    
    if topic in ["products/create", "products/update"]:
        # Sync single product to PostgreSQL + Qdrant
        product_gid = f"gid://shopify/Product/{data['id']}"
        background_tasks.add_task(sync_single_product, shop, product_gid, db)
    
    elif topic == "products/delete":
        # Remove from PostgreSQL and Qdrant
        product_gid = f"gid://shopify/Product/{data['id']}"
        db.query(Product).filter_by(shopify_gid=product_gid).delete()
        db.commit()
        
        # Delete from Qdrant using numeric ID
        try:
            numeric_id = int(product_gid.split("/")[-1])
            qdrant_client.delete(
                collection_name=QDRANT_COLLECTION,
                points_selector=[numeric_id]
            )
            print(f"✅ Deleted {product_gid} from Qdrant")
        except Exception as e:
            print(f"⚠️ Failed to delete from Qdrant: {e}")

    
    return {"status": "ok"}


@app.post("/admin/webhooks/register")
def register_webhooks(shop: str = Form(...), db: Session = Depends(get_db)):
    """
    Manual webhook registration for already-installed shops.
    Useful after config/url changes without reinstalling the app.
    """
    token = get_shop_token(db, shop)
    return ensure_product_webhooks(shop, token)

# ==================== Sync Functions ====================

def sync_shop_products(shop: str, access_token: str, db: Session):
    """Background job: Sync all products for a shop to PostgreSQL and Qdrant"""
    query = """
    query Products($first: Int!, $after: String) {
      products(first: $first, after: $after) {
        edges {
          node {
            id
            title
            handle
            descriptionHtml
            onlineStoreUrl
            featuredImage { url }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """
    
    after = None
    total_pg = 0
    total_qdrant = 0
    
    while True:
        try:
            data = shopify_graphql(shop, access_token, query, {"first": 50, "after": after})
            conn = data["data"]["products"]
            
            for edge in conn["edges"]:
                n = edge["node"]
                
                gid = n["id"]
                title = n.get("title") or ""
                handle = n.get("handle") or ""
                description = n.get("descriptionHtml") or ""
                image_url = (n.get("featuredImage") or {}).get("url") or ""
                product_url = n.get("onlineStoreUrl") or f"https://{shop}/products/{handle}"
                
                # 1. Upsert to PostgreSQL
                product = db.query(Product).filter_by(shopify_gid=gid).first()
                if not product:
                    product = Product(shop=shop, shopify_gid=gid)
                
                product.title = title
                product.description = description
                product.handle = handle
                product.image_url = image_url
                product.product_url = product_url
                
                db.add(product)
                total_pg += 1
                
                # 2. Embed and upsert to Qdrant
                try:
                    upsert_product_to_qdrant(
                        client=qdrant_client,
                        collection_name=QDRANT_COLLECTION,
                        shopify_gid=gid,
                        shop=shop,
                        title=title,
                        description=description,
                        handle=handle,
                        image_url=image_url,
                        product_url=product_url,
                        image_weight=IMAGE_WEIGHT
                    )
                    total_qdrant += 1
                    print(f"✅ Embedded: {title[:50]}")
                except Exception as e:
                    print(f"⚠️ Failed to embed {gid}: {e}")
            
            db.commit()
            
            if not conn["pageInfo"]["hasNextPage"]:
                break
            
            after = conn["pageInfo"]["endCursor"]
        
        except Exception as e:
            print(f"❌ Error syncing products for {shop}: {e}")
            break
    
    print(f"✅ Synced {total_pg} products to PostgreSQL and {total_qdrant} embeddings to Qdrant for {shop}")

def sync_single_product(shop: str, product_gid: str, db: Session):
    """Background job: Sync a single product to PostgreSQL and Qdrant"""
    token = get_shop_token(db, shop)
    
    query = """
    query GetProduct($id: ID!) {
      product(id: $id) {
        id
        title
        handle
        descriptionHtml
        onlineStoreUrl
        featuredImage { url }
      }
    }
    """
    
    try:
        data = shopify_graphql(shop, token, query, {"id": product_gid})
        n = data["data"]["product"]
        
        if not n:
            return
        
        gid = n["id"]
        title = n.get("title") or ""
        handle = n.get("handle") or ""
        description = n.get("descriptionHtml") or ""
        image_url = (n.get("featuredImage") or {}).get("url") or ""
        product_url = n.get("onlineStoreUrl") or f"https://{shop}/products/{handle}"
        
        # 1. Upsert to PostgreSQL
        product = db.query(Product).filter_by(shopify_gid=gid).first()
        if not product:
            product = Product(shop=shop, shopify_gid=gid)
        
        product.title = title
        product.description = description
        product.handle = handle
        product.image_url = image_url
        product.product_url = product_url
        
        db.add(product)
        db.commit()
        
        # 2. Embed and upsert to Qdrant
        try:
            upsert_product_to_qdrant(
                client=qdrant_client,
                collection_name=QDRANT_COLLECTION,
                shopify_gid=gid,
                shop=shop,
                title=title,
                description=description,
                handle=handle,
                image_url=image_url,
                product_url=product_url,
                image_weight=IMAGE_WEIGHT
            )
            print(f"✅ Synced and embedded product: {title}")
        except Exception as e:
            print(f"⚠️ Failed to embed product {gid}: {e}")
    
    except Exception as e:
        print(f"❌ Error syncing product {product_gid} for {shop}: {e}")

# ==================== Search API (for storefront widget) ====================

@app.post("/api/search/text")
def search_text(query: str = Form(...), shop: str = Form(None), db: Session = Depends(get_db)):
    """
    Optimized text search with 2-tier fallback:
    1. PostgreSQL ILIKE (fastest regex)
    2. Qdrant fused embedding vector search (semantic)
    """
    if not query or not query.strip():
        return {"products": []}

    query_lower = query.lower().strip()

    # Step 1: Try PostgreSQL ILIKE (fastest)
    patterns = [
        f"% {query_lower} %",   # surrounded by spaces
        f"% {query_lower}",     # at end
        f"{query_lower} %",     # at start
        f"{query_lower}"        # exact
    ]

    sql_query = db.query(Product).filter(
        or_(
            *[func.lower(Product.title).like(p) for p in patterns],
            *[func.lower(Product.description).like(p) for p in patterns]
        )
    )

    if shop:
        sql_query = sql_query.filter(Product.shop == shop)

    rows = sql_query.limit(10).all()

    products = [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description[:200] if r.description else "",
            "price": "0.00",
            "handle": r.handle,
            "image_url": r.image_url,
            "product_url": r.product_url,
            "score": 1.0,
            "source": "postgresql"
        }
        for r in rows
    ]

    # Step 2: Top up with fused embedding search if PostgreSQL returned < 10
    if len(products) < 10:
        try:
            print(f"Fused embedding top-up for: '{query}'")

            query_vector = encode_text_embedding(query)
            print(f"Query embedding sample: {query_vector[:10]}")
            print(f"Query embedding length: {len(query_vector)}")

            search_filter = None
            if shop:
                search_filter = Filter(must=[FieldCondition(key="shop", match=MatchValue(value=shop))])
                print(f"Filtering by shop: {shop}")

            remaining = 10 - len(products)
            existing_gids = {r.shopify_gid for r in rows}

            search_result = qdrant_client.query_points(
                collection_name=QDRANT_COLLECTION,
                query=query_vector,
                using="fused",
                query_filter=search_filter,
                limit=remaining + 10,
                score_threshold=0.3,
            )

            points = search_result.points if hasattr(search_result, "points") else search_result
            print(f"[fused] Found {len(points)} results")

            score_map = {}
            topup_gids = []
            for p in points:
                gid = p.payload["shopify_gid"]
                if gid in existing_gids or gid in score_map:
                    continue
                score_map[gid] = round(p.score, 4)
                topup_gids.append(gid)
                if len(topup_gids) >= remaining:
                    break

            if topup_gids:
                extra_rows = db.query(Product).filter(Product.shopify_gid.in_(topup_gids)).all()
                extra_rows_sorted = sorted(extra_rows, key=lambda x: score_map.get(x.shopify_gid, 0), reverse=True)

                products.extend(
                    [
                        {
                            "id": r.id,
                            "title": r.title,
                            "description": r.description[:200] if r.description else "",
                            "price": "0.00",
                            "handle": r.handle,
                            "image_url": r.image_url,
                            "product_url": r.product_url,
                            "score": score_map.get(r.shopify_gid, 0.5),
                            "source": "qdrant_embedding"
                        }
                        for r in extra_rows_sorted
                    ]
                )
        except Exception as e:
            print(f"Qdrant fused embedding search failed: {e}")
            import traceback
            traceback.print_exc()

    return {"products": products[:10]}

@app.post("/api/search/image")
async def search_image(
    image: UploadFile = File(...),
    shop: str = Form(None),
    db: Session = Depends(get_db)
):
    """Search products by uploaded image using image embedding."""
    try:
        # Read uploaded image
        print(f"📸 Received image: {image.filename}, content_type: {image.content_type}, size: {image.size if hasattr(image, 'size') else 'unknown'}")
        
        contents = await image.read()
        print(f"📸 Read {len(contents)} bytes")
        
        image_pil = Image.open(io.BytesIO(contents)).convert("RGB")
        print(f"📸 Image opened: {image_pil.size}, mode: {image_pil.mode}")
        # Embed query image
        query_vector = encode_image_embedding(image_pil)
        
        # Debug: Print first 10 values of embedding
        print(f"📸 Query embedding sample: {query_vector[:10]}")
        print(f"📸 Query embedding length: {len(query_vector)}")
        
        # Build filter
        search_filter = None
        if shop:
            search_filter = Filter(must=[FieldCondition(key="shop", match=MatchValue(value=shop))])
            print(f"📸 Filtering by shop: {shop}")
        
        # Search Qdrant with image vector
        search_result = qdrant_client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query_vector,
            using="image",
            query_filter=search_filter,
            limit=10,
            score_threshold=0.3,  # Lowered threshold
        )
        
        results = search_result.points if hasattr(search_result, 'points') else search_result
        
        # Debug: Print all results with scores
        print(f"📸 Found {len(results)} results:")
        for r in results:
            print(f"  - {r.payload.get('title', 'N/A')} (score: {r.score:.4f})")
        
        if not results:
            print("📸 No results found")
            return {"products": []}
        
        # Get full product data from PostgreSQL
        shopify_gids = [r.payload["shopify_gid"] for r in results]
        rows = db.query(Product).filter(Product.shopify_gid.in_(shopify_gids)).all()
        
        # Create score map and sort by score
        score_map = {r.payload["shopify_gid"]: r.score for r in results}
        rows_sorted = sorted(rows, key=lambda x: score_map.get(x.shopify_gid, 0), reverse=True)
        
        return {
            "products": [
                {
                    "id": r.id,
                    "title": r.title,
                    "description": r.description[:200] if r.description else "",
                    "price": "0.00",
                    "handle": r.handle,
                    "image_url": r.image_url,
                    "product_url": r.product_url,
                    "score": round(score_map.get(r.shopify_gid, 0.5), 4),
                    "source": "image_search"
                }
                for r in rows_sorted
            ]
        }
    
    except Exception as e:
        print(f"❌ Image search error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Image search failed: {str(e)}")

@app.get("/admin/sync-status")
def sync_status(shop: str, db: Session = Depends(get_db)):
    """Check sync status for a shop"""
    try:
        # Check if shop is installed
        token = get_shop_token(db, shop)
        
        # Count products in PostgreSQL
        pg_count = db.query(Product).filter_by(shop=shop).count()
        
        # Count products in Qdrant (approximate via scroll)
        search_filter = Filter(must=[FieldCondition(key="shop", match=MatchValue(value=shop))])
        qdrant_result, _ = qdrant_client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=search_filter,
            limit=100,
            with_payload=False,
            with_vectors=False
        )
        
        qdrant_count = len(qdrant_result)
        
        return {
            "shop": shop,
            "postgresql_products": pg_count,
            "qdrant_embeddings": qdrant_count,
            "status": "synced" if pg_count > 0 and qdrant_count > 0 else "syncing"
        }
    except HTTPException:
        return {"shop": shop, "status": "not_installed"}

@app.get("/health")
def health():
    return {"status": "ok", "service": "wakubo-semantic-search-backend"}

