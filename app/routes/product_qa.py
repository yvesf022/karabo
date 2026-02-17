from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Product, ProductQuestion, ProductAnswer
from app.dependencies import get_current_user

router = APIRouter(prefix="/products", tags=["product-qa"])


class QuestionCreate(BaseModel):
    question: str


class AnswerCreate(BaseModel):
    answer: str


@router.post("/{product_id}/questions", status_code=status.HTTP_201_CREATED)
def create_question(
    product_id: str,
    payload: QuestionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ask a question about a product."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    question = ProductQuestion(
        product_id=product_id,
        user_id=user.id,
        question=payload.question,
    )
    db.add(question)
    db.commit()
    db.refresh(question)

    return {"message": "Question submitted", "question_id": str(question.id)}


@router.get("/{product_id}/questions", status_code=status.HTTP_200_OK)
def get_product_questions(
    product_id: str,
    db: Session = Depends(get_db),
):
    """Get all questions for a product."""
    questions = (
        db.query(ProductQuestion)
        .options(
            joinedload(ProductQuestion.user),
            joinedload(ProductQuestion.answers).joinedload(ProductAnswer.user)
        )
        .filter(ProductQuestion.product_id == product_id)
        .order_by(ProductQuestion.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(q.id),
            "question": q.question,
            "user_name": q.user.full_name if q.user else "Anonymous",
            "created_at": q.created_at,
            "answers": [
                {
                    "id": str(a.id),
                    "answer": a.answer,
                    "user_name": a.user.full_name if a.user else "Anonymous",
                    "is_seller": a.is_seller,
                    "created_at": a.created_at,
                }
                for a in q.answers
            ],
        }
        for q in questions
    ]


@router.post("/questions/{question_id}/answer", status_code=status.HTTP_201_CREATED, tags=["product-qa"])
def answer_question(
    question_id: str,
    payload: AnswerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Answer a product question."""
    question = db.query(ProductQuestion).filter(ProductQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    answer = ProductAnswer(
        question_id=question_id,
        user_id=user.id,
        answer=payload.answer,
        is_seller=user.is_admin,
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    return {"message": "Answer submitted", "answer_id": str(answer.id)}
