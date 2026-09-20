# Dikhao Architecture

## System Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                        DIKHAO - AI Shopping App                    │
└────────────────────────────────────────────────────────────────────┘

┌─────────────────────────┐
│   FRONTEND (React/HTML)  │
├─────────────────────────┤
│ 1. Landing Page         │
│ 2. Input (Img/Text/Vo)  │
│ 3. AI Intent Display    │
│ 4. Product Comparison   │
│ 5. Constraint Verify    │
│ 6. Purchase Confirm     │
│ 7. Order Tracking       │
└────────┬────────────────┘
         │ HTTP POST
         ↓
    ┌──────────────────────────────────────────────────────────┐
    │           MAKE.COM ORCHESTRATION LAYER                  │
    ├──────────────────────────────────────────────────────────┤
    │                                                          │
    │  Module 1: Webhook                                      │
    │  ├─ Receives: { image, text, voice, user_id }          │
    │  │                                                      │
    │  Module 2: Parse & Validate                            │
    │  ├─ Extract input components                           │
    │  │                                                      │
    │  Module 4: Claude AI (Intent)                          │
    │  ├─ INPUT:  "minimalist white sneakers"               │
    │  ├─ OUTPUT: {                                           │
    │  │   "category": "fashion",                            │
    │  │   "style": "minimalist",                            │
    │  │   "budget": 5000,                                   │
    │  │   "occasion": "daily",                              │
    │  │   "must_have": ["comfortable", "durable"]           │
    │  │ }                                                    │
    │  │                                                      │
    │  Module 6: Product Search API                          │
    │  ├─ API: /products?category=fashion&limit=20           │
    │  ├─ SOURCE: DummyJSON (demo) → Your DB (prod)         │
    │  ├─ RETURNS: Array of products                         │
    │  │                                                      │
    │  Module 7: Iterator                                    │
    │  ├─ Loop through each product                          │
    │  │                                                      │
    │  Module 8: Score & Filter                              │
    │  ├─ HARD CONSTRAINTS (Deterministic):                  │
    │  │   ✓ inBudget = product.price ≤ 5000                │
    │  │   ✓ inStock = product.stock > 0                     │
    │  │   ✓ delivery <= 7 days                              │
    │  ├─ SOFT SCORING:                                       │
    │  │   + 25 if category matches                          │
    │  │   + 15 if rating >= 4.5                             │
    │  │   + 10 if within budget                             │
    │  ├─ PASSES = all hard constraints met                  │
    │  │                                                      │
    │  Module 9: Filter (Keep Passing)                       │
    │  ├─ condition: passes_constraints == true              │
    │  │                                                      │
    │  Module 10: Aggregator                                 │
    │  ├─ Combine all passing products                       │
    │  │                                                      │
    │  Module 11: Rank & Select Top 3                        │
    │  ├─ Sort by: match_score DESC                          │
    │  ├─ Limit: 3 products                                  │
    │  ├─ OUTPUT: [                                           │
    │  │   { id: 1, name: "...", score: 98 },               │
    │  │   { id: 2, name: "...", score: 85 },               │
    │  │   { id: 3, name: "...", score: 72 }                │
    │  │ ]                                                    │
    │  │                                                      │
    │  Module 12: Router (Products Found?)                   │
    │  ├─ Route 1: YES (≥1 product) → Purchase flow         │
    │  ├─ Route 2: NO (0 products) → "No match" notice       │
    │  │                                                      │
    │  ┌─ ROUTE 1: PURCHASE FLOW                             │
    │  │                                                      │
    │  │ Module 13: Create Purchase Order                    │
    │  │ ├─ API: POST /orders                                │
    │  │ ├─ Payload: {                                       │
    │  │ │   product_id: 1,                                  │
    │  │ │   user_id: "...",                                │
    │  │ │   amount: 4999,                                   │
    │  │ │   tax: 900,                                       │
    │  │ │   shipping: 99                                    │
    │  │ │ }                                                  │
    │  │ ├─ RETURNS: { order_id: "ORD1726756340000" }       │
    │  │ │                                                    │
    │  │ Module 14: Confirm Order                           │
    │  │ ├─ Store in database                               │
    │  │ ├─ Generate tracking link                          │
    │  │ ├─ Calculate delivery date (+3 days)               │
    │  │ │                                                    │
    │  │ Module 15: Send Notification                        │
    │  │ ├─ METHOD: Email / SMS / Push                       │
    │  │ ├─ TEMPLATE: "Order {id} confirmed, delivery {date}"│
    │  │ ├─ RECIPIENT: user.email / user.phone              │
    │  │                                                      │
    │  └─ ROUTE 2: NO MATCH                                  │
    │                                                      │
    │    Module 16: Notify "No Match"                        │
    │    ├─ Send: "No products found matching your style"   │
    │    ├─ Suggest: "Try different budget or occasion"     │
    │                                                      │
    └──────────────────────────────────────────────────────────┘
         │ HTTP Response (JSON)
         ↓
┌─────────────────────────┐
│  FRONTEND (React/HTML)   │
├─────────────────────────┤
│ Show Results:            │
│ - Products (ranked)      │
│ - Order confirmation     │
│ - Tracking status        │
└─────────────────────────┘
```

---

## Detailed Module Breakdown

### Module 1: Webhook (Trigger)
**Type:** Custom Webhook
**Listens for:** POST request
**Expected payload:**
```json
{
  "image": "data:image/...",      // Optional: base64 image
  "text": "minimalist sneakers",   // Optional: text description
  "voice": "transcribed text",     // Optional: voice transcription
  "user_id": "user123"             // Required: user identifier
}
```

---

### Module 2: Parse & Validate
**Type:** Code Execute
**Process:**
1. Extract input type (image/text/voice)
2. Validate at least one input provided
3. Timestamp the request
4. Pass to AI module

**Output:**
```json
{
  "raw_input": {...},
  "input_type": "text",
  "has_content": true
}
```

---

### Module 4: Claude AI Analysis
**Type:** Claude Module (via MCP)
**Prompt:**
```
Analyze this shopping request and extract intent:
Input: {text or image description}
Image provided: {yes/no}

Respond with ONLY valid JSON:
{
  "category": "fashion|electronics|home|...",
  "style": "minimalist|vintage|modern|...",
  "occasion": "daily|party|work|...",
  "budget": {amount in local currency},
  "must_have": ["feature1", "feature2"],
  "preferred": ["feature3", "feature4"],
  "description": "full request text"
}
```

**Why Claude:** 
- Understands multimodal context
- Handles vague descriptions
- Extracts structured intent from unstructured input
- Culturally aware (Indian pricing, occasions, etc.)

---

### Module 6: Product Search API
**Type:** HTTP GET Request
**Current (Demo):**
```
https://dummyjson.com/products?limit=20&skip=0
```

**Production (Replace with):**
```
https://your-api.com/search?
  category={intent.category}
  &max_price={intent.budget}
  &limit=20
```

**Response format required:**
```json
{
  "products": [
    {
      "id": 1,
      "title": "Product Name",
      "price": 4999,
      "rating": 4.8,
      "stock": 12,
      "category": "shoes",
      ...
    }
  ]
}
```

---

### Module 8: Constraint Filter & Scoring
**Type:** Code Execute
**Hard Constraints (Deterministic):**
```javascript
const inBudget = product.price <= intent.budget;    // HARD
const hasStock = product.stock > 0;                 // HARD
const delivery = product.delivery_days <= 7;        // HARD
const passes = inBudget && hasStock && delivery;    // BOOLEAN
```

**Soft Scoring (AI Preference):**
```javascript
let score = 50;  // Base score
score += 25 if category_match;    // Category relevance
score += 15 if rating >= 4.5;     // Quality signal
score += 10 if within_budget;     // Budget fit
// Final: 50-100 range
```

**Key insight:** Only products where `passes === true` reach recommendations. Budget is verified deterministically, not estimated.

---

### Module 9: Filter
**Type:** Basic Filter
**Condition:**
```
{{ module8.passes_constraints === true }}
```
**Effect:** Removes products that fail hard constraints

---

### Module 11: Rank & Select Top 3
**Type:** Code Execute
**Algorithm:**
```javascript
const sorted = products
  .filter(p => p.passes_constraints)
  .sort((a, b) => b.match_score - a.match_score)
  .slice(0, 3);

return {
  recommended_products: sorted,
  total_options: sorted.length
}
```

**Why top 3:** 
- Avoids paradox of choice
- Reduces decision fatigue
- Faster validation at hackathon
- Production: configurable

---

### Module 13: Mock Purchase API
**Type:** HTTP POST
**Current (Demo):** `https://mock-purchase-api.example.com/orders`

**Payload:**
```json
{
  "product_id": 1,
  "user_id": "user123",
  "amount": 4999,
  "tax": 900,
  "shipping": 99,
  "timestamp": "2026-09-20T14:30:45Z"
}
```

**Response:**
```json
{
  "order_id": "ORD1726756340000",
  "status": "confirmed",
  "delivery_date": "2026-09-23"
}
```

**Production replacements:**
- **Stripe:** `https://api.stripe.com/v1/charges`
- **Razorpay:** `https://api.razorpay.com/v1/orders`
- **PayPal:** `https://api.sandbox.paypal.com/v1/payments/payment`
- **Your backend:** `https://your-api.com/orders`

---

### Module 15: Notification
**Type:** Email / SMS / HTTP POST
**Options:**

**Option 1: Email (Make's Email module)**
```
To: user.email
Subject: Your Dikhao order {{order_id}} confirmed
Body: Your order is confirmed. Delivery {{delivery_date}}. Track: {{tracking_link}}
```

**Option 2: Webhook (Your backend)**
```json
{
  "order_id": "ORD...",
  "status": "confirmed",
  "user_id": "user123",
  "notification_type": "order_confirmation"
}
```

**Option 3: SMS (Twilio, AWS SNS)**
```
Hi, your order ORD... confirmed! Delivery on Sept 23. Track: link
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ USER INPUT                                                      │
│ Image: "Instagram post of white sneakers"                       │
│ OR Text: "minimalist white sneakers under 5000"                │
│ OR Voice: [transcribed] "show me white sneakers"               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓ (Webhook POST)
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 1-2: Parse Input                                   │
│ Extract: image_data, text, voice_text                         │
│ Validate: at_least_one_input_exists                           │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 4: Claude AI → Shopping Intent                    │
│ INPUT:  "minimalist white sneakers"                           │
│ PROCESS: NLP analysis                                         │
│ OUTPUT:  {                                                     │
│   category: "fashion",                                        │
│   style: "minimalist",                                        │
│   budget: 5000,                                               │
│   must_have: ["comfortable", "durable"],                      │
│   preferred: ["waterproof", "eco-friendly"]                   │
│ }                                                              │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 6: Product Search API                             │
│ QUERY: /products?category=fashion&max_price=5000              │
│ RETURN: [                                                      │
│   { id: 1, name: "White Sneaker", price: 4999, stock: 12 },  │
│   { id: 2, name: "Leather Shoe", price: 6500, stock: 5 },    │
│   { id: 3, name: "Sport Shoe", price: 3999, stock: 20 },     │
│   ... (20 products total)                                      │
│ ]                                                              │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓ (Module 7: Iterator)
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 8-9: CONSTRAINT FILTERING (For each product)      │
│                                                                │
│ Product #1: White Sneaker (₹4999)                             │
│ ├─ inBudget? 4999 ≤ 5000 → YES ✅                             │
│ ├─ hasStock? 12 > 0 → YES ✅                                  │
│ ├─ delivery? 2 days → YES ✅                                  │
│ ├─ passes_constraints → TRUE → KEEP                           │
│ ├─ match_score → 98% (minimalist match + rating 4.8)         │
│                                                                │
│ Product #2: Leather Shoe (₹6500)                              │
│ ├─ inBudget? 6500 ≤ 5000 → NO ❌                              │
│ ├─ passes_constraints → FALSE → FILTER OUT                    │
│                                                                │
│ Product #3: Sport Shoe (₹3999)                                │
│ ├─ inBudget? 3999 ≤ 5000 → YES ✅                             │
│ ├─ hasStock? 20 > 0 → YES ✅                                  │
│ ├─ delivery? 2 days → YES ✅                                  │
│ ├─ passes_constraints → TRUE → KEEP                           │
│ ├─ match_score → 72% (sports style, not minimalist)          │
│                                                                │
│ ... (repeat for all 20 products)                             │
│                                                                │
│ RESULT: Only products where passes_constraints=TRUE survive   │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓ (Module 10-11: Aggregate & Rank)
                         
┌────────────────────────────────────────────────────────────────┐
│ RECOMMENDATION RESULTS (Top 3, Ranked by match_score)         │
│                                                                │
│ 1. BEST MATCH (98%)                                           │
│    White Sneaker                                              │
│    Price: ₹4999 | Rating: 4.8/5 | Stock: 12                 │
│    Why: minimalist style, within budget, highly rated        │
│                                                                │
│ 2. GOOD MATCH (85%)                                           │
│    Classic Leather Sneaker                                    │
│    Price: ₹5990 | Rating: 4.6/5 | Stock: 5                  │
│    Why: great style match                                     │
│    Why not: Exceeds budget by ₹990                           │
│                                                                │
│ 3. ALTERNATIVE (72%)                                          │
│    Sport Performance Shoe                                     │
│    Price: ₹3999 | Rating: 4.4/5 | Stock: 20                 │
│    Why: budget-friendly, good stock                          │
│    Why not: sports style, not minimalist                      │
└────────────────────────┬──────────────────────────────────────┘
                         │
                    (User selects #1)
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 12: ROUTER                                        │
│ Condition: products_found > 0? YES                            │
│ Route: PURCHASE_FLOW                                          │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ FRONTEND: CONSTRAINT VERIFICATION SCREEN                       │
│                                                                │
│ User sees:                                                     │
│ ✅ Budget: ₹4999 ≤ ₹5000                                      │
│ ✅ In Stock: 12 units available                               │
│ ✅ Delivery: Ships in 2-3 days                                │
│ ✅ Features: Comfortable ✓, Durable ✓                         │
│                                                                │
│ Order Summary:                                                │
│ Product Price: ₹4999                                          │
│ Tax (18%): ₹900                                               │
│ Shipping: ₹99                                                 │
│ TOTAL: ₹5,998                                                 │
│                                                                │
│ [Confirm purchase]                                            │
└────────────────────────┬──────────────────────────────────────┘
                         │
                    (User clicks confirm)
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 13: CREATE PURCHASE ORDER                         │
│ POST /orders                                                   │
│ {                                                              │
│   "product_id": 1,                                            │
│   "user_id": "user123",                                       │
│   "amount": 4999,                                             │
│   "tax": 900,                                                 │
│   "shipping": 99                                              │
│ }                                                              │
│                                                                │
│ Response:                                                      │
│ {                                                              │
│   "order_id": "ORD1726756340000",                            │
│   "status": "confirmed"                                       │
│ }                                                              │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 14: CONFIRM ORDER                                 │
│ ✓ Store in database                                           │
│ ✓ Generate tracking ID                                        │
│ ✓ Calculate delivery date: Sept 23, 2026                      │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ MAKE MODULE 15: SEND NOTIFICATION                             │
│ Email to user123@email.com:                                   │
│ "Your Dikhao order ORD1726756340000 is confirmed!             │
│  Expected delivery: Sept 23, 2026                             │
│  Track: https://tracking.example.com/ORD..."                  │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ FRONTEND: ORDER SUCCESS SCREEN                                │
│                                                                │
│ ✅ Order placed!                                              │
│ Order ID: ORD1726756340000                                   │
│ Product: Premium White Sneaker                                │
│ Delivery: September 23, 2026                                  │
│                                                                │
│ [Track order] [Shop again]                                    │
└────────────────────────┬──────────────────────────────────────┘
                         │
                    (User clicks Track)
                         │
                         ↓
                         
┌────────────────────────────────────────────────────────────────┐
│ FRONTEND: ORDER TRACKING SCREEN                               │
│                                                                │
│ ✓ Order Placed         Just now                              │
│ ✓ Payment Confirmed    2 mins ago                            │
│ • Preparing to Ship    In progress                           │
│ ○ Out for Delivery     Estimated tomorrow                    │
│                                                                │
│ Timeline animates as order progresses                        │
└────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React / HTML5 | UI/UX, user interaction |
| **Orchestration** | Make.com | Workflow automation, API coordination |
| **AI** | Claude (via MCP) | Multimodal intent analysis |
| **Product DB** | DummyJSON / Your API | Product catalog |
| **Payment** | Mock / Stripe / Razorpay | Order processing |
| **Notifications** | Email / SMS / Webhook | User communication |
| **Database** | Your backend | Orders, users, tracking |

---

## Error Handling

```
If products_found == 0
├─ No products match
├─ Notify user: "Try different budget or occasion"
└─ Suggest: "Adjust your preferences and retry"

If Claude intent fails
├─ Return generic intent: { category: "general", budget: 5000 }
└─ Continue with search

If product API times out
├─ Retry up to 2 times
├─ If still fails, return error to user
└─ Suggest: "Try again later"

If payment fails
├─ Roll back order
├─ Show error: "Payment declined. Try another method."
└─ Keep product selected for retry

If notification fails
├─ Log to system
├─ User can view order in account
└─ Retry notification delivery hourly
```

---

## Performance Optimization

**Frontend:**
- Lazy load images
- Minimize CSS/JS bundle
- Cache product images

**Make.com:**
- Cache Claude API responses (same intent = same products)
- Batch product search (single API call vs. per-product)
- Use Iterator + BasicFilter (built-in optimization)

**Backend:**
- Index products by category, price range
- Pre-compute match scores
- CDN for images

---

**Architecture Version:** 1.0
**Last Updated:** September 20, 2026
