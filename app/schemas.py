"""Pydantic Contracts & Validation Schemas for Phoenix Shopper Assistant."""

from typing import Any, Dict, List, Literal, Optional
try:
    from pydantic import BaseModel, Field
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def model_dump(self) -> Dict[str, Any]:
            res = {}
            for k, v in self.__dict__.items():
                if isinstance(v, list):
                    res[k] = [item.model_dump() if hasattr(item, "model_dump") else item for item in v]
                elif hasattr(v, "model_dump"):
                    res[k] = v.model_dump()
                else:
                    res[k] = v
            return res
        def __repr__(self):
            return f"{self.__class__.__name__}({self.__dict__})"

    def Field(default=None, default_factory=None, **kwargs):
        if default_factory is not None:
            return default_factory()
        return default



AnswerType = Literal[
    "product_recommendation",
    "product_comparison",
    "order_status",
    "clarification",
    "guardrail_blocked",
    "general_info",
]


class ProductBase(BaseModel):
    product_id: str = Field(..., description="Unique product SKU or identifier")
    title: str = Field(..., description="Product title")
    description: str = Field(..., description="Detailed product description")
    category: str = Field(..., description="Category, e.g. Electronics, Footwear")
    brand: str = Field(..., description="Manufacturer or brand")
    price: float = Field(..., ge=0, description="Product price in currency unit")
    currency: str = Field(default="INR", description="Currency symbol/code, e.g. INR, USD")
    stock_quantity: int = Field(default=0, ge=0, description="Available stock count")
    rating: float = Field(default=0.0, ge=0.0, le=5.0, description="Average customer rating out of 5")
    specs: Dict[str, Any] = Field(default_factory=dict, description="Key-value specifications (RAM, color, size, etc.)")
    tags: List[str] = Field(default_factory=list, description="Keywords and tags")
    multilingual_titles: Dict[str, str] = Field(
        default_factory=dict, description="Translations/local names (e.g. hi, es, hinglish)"
    )


class ProductCreate(ProductBase):
    pass


class ProductSummary(BaseModel):
    product_id: str
    title: str
    category: str
    brand: str
    price: float
    currency: str
    stock_quantity: int
    rating: float
    specs: Dict[str, Any] = Field(default_factory=dict)
    score: Optional[float] = Field(default=None, description="Relevance score from hybrid search")


class Shopper(BaseModel):
    customer_id: str = Field(..., description="Unique shopper ID, e.g. C001")
    name: str = Field(..., description="Customer full name")
    email: str = Field(..., description="Customer email address")
    loyalty_tier: str = Field(default="Bronze", description="Bronze, Silver, Gold, Platinum")
    address: Optional[str] = None
    created_at: Optional[str] = None


class OrderItem(BaseModel):
    order_id: str
    customer_id: str
    product_id: str
    product_title: Optional[str] = None
    quantity: int = Field(..., gt=0)
    total_amount: float = Field(..., ge=0)
    order_status: str = Field(..., description="Delivered, Shipped, Processing, Cancelled")
    order_date: str
    tracking_number: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, description="Session ID for ongoing conversation context")
    customer_id: Optional[str] = Field(default=None, description="Shopper identity (required for private order queries)")
    query: str = Field(..., min_length=1, description="Shopper natural language message")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Optional explicit hard filters")


class ChatResponse(BaseModel):
    trace_id: str = Field(..., description="Unique audit trace identifier for debugging")
    session_id: str = Field(..., description="Conversation session ID")
    customer_id: Optional[str] = Field(default=None)
    answer: str = Field(..., description="Grounded, synthesized assistant response")
    answer_type: AnswerType = Field(..., description="Categorization of the answer for UI rendering & eval")
    products: List[ProductSummary] = Field(default_factory=list, description="Relevant product items")
    orders: List[OrderItem] = Field(default_factory=list, description="Relevant order items if query was order-related")
    active_filters: Dict[str, Any] = Field(default_factory=dict, description="Filters applied to retrieve products")
    latency_ms: float = Field(..., description="Total processing latency in milliseconds")


class IngestRequest(BaseModel):
    products: List[ProductCreate]


class IngestResponse(BaseModel):
    ingested_count: int
    message: str


class TraceRecord(BaseModel):
    trace_id: str
    timestamp: str
    session_id: Optional[str] = None
    customer_id: Optional[str] = None
    user_query: str
    normalized_query: str
    guardrail_flags: Dict[str, Any] = Field(default_factory=dict)
    intent: str
    parsed_filters: Dict[str, Any] = Field(default_factory=dict)
    retrieved_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    applied_hard_filters: Dict[str, Any] = Field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    llm_plan: Dict[str, Any] = Field(default_factory=dict)
    latency_breakdown: Dict[str, float] = Field(default_factory=dict)
    total_latency_ms: float
    final_answer_type: str
