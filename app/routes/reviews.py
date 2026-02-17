from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import User, Review, ReviewVote, Product
from app.dependencies import get_current_user

router = APIRouter(prefix="/reviews", tags=["reviews"])


# =====================================================
# Pydantic Schemas
# =====================================================

class ReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    title: Optional[str] = None
    comment: Optional[str] = None


class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    title: Optional[str] = None
    comment: Optional[str] = None


class ReviewVotePayload(BaseModel):
    is_helpful: bool


# =====================================================
# USER: CREATE REVIEW
# =====================================================
@router.post("/products/{product_id}/reviews", status_code=status.HTTP_201_CREATED, tags=["products"])
def create_review(
    product_id: str,
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a review for a product."""
    # Check product exists
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if user already reviewed
    existing = (
        db.query(Review)
        .filter(Review.product_id == product_id, Review.user_id == user.id)
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="You already reviewed this product")

    review = Review(
        product_id=product_id,
        user_id=user.id,
        rating=payload.rating,
        title=payload.title,
        comment=payload.comment,
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    # Update product rating
    avg_rating = db.query(func.avg(Review.rating)).filter(Review.product_id == product_id).scalar()
    rating_count = db.query(func.count(Review.id)).filter(Review.product_id == product_id).scalar()
    
    product.rating = round(float(avg_rating), 2) if avg_rating else 0
    product.rating_number = rating_count
    db.commit()

    return {
        "message": "Review created",
        "review_id": str(review.id),
        "rating": review.rating,
    }


# =====================================================
# USER: UPDATE REVIEW
# =====================================================
@router.patch("/{review_id}", status_code=status.HTTP_200_OK)
def update_review(
    review_id: str,
    payload: ReviewUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update user's own review."""
    review = (
        db.query(Review)
        .filter(Review.id == review_id, Review.user_id == user.id)
        .first()
    )

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    updated_fields = payload.dict(exclude_unset=True)

    if not updated_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    for field, value in updated_fields.items():
        setattr(review, field, value)

    db.commit()
    db.refresh(review)

    # Recalculate product rating if rating changed
    if "rating" in updated_fields:
        product = db.query(Product).filter(Product.id == review.product_id).first()
        avg_rating = db.query(func.avg(Review.rating)).filter(Review.product_id == review.product_id).scalar()
        product.rating = round(float(avg_rating), 2) if avg_rating else 0
        db.commit()

    return {
        "message": "Review updated",
        "review_id": str(review.id),
    }


# =====================================================
# USER: DELETE REVIEW
# =====================================================
@router.delete("/{review_id}", status_code=status.HTTP_200_OK)
def delete_review(
    review_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete user's own review."""
    review = (
        db.query(Review)
        .filter(Review.id == review_id, Review.user_id == user.id)
        .first()
    )

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    product_id = review.product_id
    
    db.delete(review)
    db.commit()

    # Recalculate product rating
    product = db.query(Product).filter(Product.id == product_id).first()
    avg_rating = db.query(func.avg(Review.rating)).filter(Review.product_id == product_id).scalar()
    rating_count = db.query(func.count(Review.id)).filter(Review.product_id == product_id).scalar()
    
    product.rating = round(float(avg_rating), 2) if avg_rating else 0
    product.rating_number = rating_count
    db.commit()

    return {"message": "Review deleted"}


# =====================================================
# USER: GET MY REVIEWS
# =====================================================
@router.get("/users/me/reviews", status_code=status.HTTP_200_OK, tags=["users"])
def get_my_reviews(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all reviews by current user."""
    reviews = (
        db.query(Review)
        .options(joinedload(Review.product))
        .filter(Review.user_id == user.id)
        .order_by(Review.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(r.id),
            "product_id": str(r.product_id),
            "product_title": r.product.title if r.product else None,
            "rating": r.rating,
            "title": r.title,
            "comment": r.comment,
            "helpful_count": r.helpful_count,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in reviews
    ]


# =====================================================
# USER: VOTE ON REVIEW
# =====================================================
@router.post("/{review_id}/vote", status_code=status.HTTP_200_OK)
def vote_review(
    review_id: str,
    payload: ReviewVotePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Vote on a review (helpful/not helpful)."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    # Check if already voted
    existing_vote = (
        db.query(ReviewVote)
        .filter(ReviewVote.review_id == review_id, ReviewVote.user_id == user.id)
        .first()
    )

    if existing_vote:
        # Update vote
        old_helpful = existing_vote.is_helpful
        existing_vote.is_helpful = payload.is_helpful
        
        # Adjust helpful count
        if old_helpful and not payload.is_helpful:
            review.helpful_count -= 1
        elif not old_helpful and payload.is_helpful:
            review.helpful_count += 1
    else:
        # Create new vote
        vote = ReviewVote(
            review_id=review_id,
            user_id=user.id,
            is_helpful=payload.is_helpful,
        )
        db.add(vote)
        
        if payload.is_helpful:
            review.helpful_count += 1

    db.commit()

    return {
        "message": "Vote recorded",
        "helpful_count": review.helpful_count,
    }
