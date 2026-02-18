from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginData(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username must be alphanumeric")
        return value


class SignupData(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username must be alphanumeric")
        return value


class ChatMessage(BaseModel):
    topic_id: Optional[str] = Field(None, max_length=100)
    chat_id: Optional[str] = Field(None, max_length=100)
    subject: Optional[str] = Field(None, max_length=60)
    chat_mode: Optional[str] = Field(None, max_length=20)
    extra_context: Optional[str] = Field(None, max_length=20000)
    message: str = Field(..., min_length=1, max_length=2000)


class UpdateProfileData(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)


class AccountSettingsData(BaseModel):
    web_search_enabled: bool = True
    save_chat_history: bool = True
    study_reminders_enabled: bool = False
    grade_level: Optional[str] = Field("", max_length=30)
    education_board: Optional[str] = Field("", max_length=50)


class UpdatePasswordData(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class LearningAssetData(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    content: str = Field(..., min_length=10, max_length=12000)
    chat_id: Optional[str] = Field(None, max_length=100)


class AddSourceData(BaseModel):
    domain: str = Field(..., min_length=3, max_length=100)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        value = value.strip().lower()
        if "." not in value or " " in value:
            raise ValueError("Invalid domain format")
        return value


class SubjectPresetData(BaseModel):
    subject: str = Field(..., min_length=2, max_length=60)


class SubjectPresetOrderData(BaseModel):
    preset_ids: list[str] = Field(..., min_length=1)


class RefreshTokenData(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class UpdateDocumentSubjectData(BaseModel):
    subject: str = Field(..., min_length=2, max_length=60)


class GenerateCourseData(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=30)
    title: Optional[str] = Field(None, max_length=120)
    request: Optional[str] = Field(None, max_length=2000)
    start_date: str = Field(..., min_length=10, max_length=10)
    duration_days: int = Field(14, ge=7, le=90)


class GenerateQuizData(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=30)
    topic: Optional[str] = Field(None, max_length=120)
    request: Optional[str] = Field(None, max_length=2000)
    question_count: int = Field(8, ge=3, le=25)


class EvaluateQuizAnswerData(BaseModel):
    quiz_id: str = Field(..., min_length=1, max_length=100)
    question: str = Field(..., min_length=5, max_length=5000)
    user_answer: str = Field(..., min_length=1, max_length=5000)
    question_index: Optional[int] = Field(None, ge=1, le=200)
    total_questions: Optional[int] = Field(None, ge=1, le=200)


class PlannerBusySlotData(BaseModel):
    date: str = Field(..., min_length=10, max_length=10)
    start_time: str = Field(..., min_length=4, max_length=5)
    end_time: str = Field(..., min_length=4, max_length=5)
    title: Optional[str] = Field("Busy", max_length=120)


class PlannerTaskData(BaseModel):
    date: str = Field(..., min_length=10, max_length=10)
    title: str = Field(..., min_length=2, max_length=180)
    time: Optional[str] = Field(None, min_length=4, max_length=5)
    notes: Optional[str] = Field(None, max_length=1000)


class PlannerReminderData(BaseModel):
    date: str = Field(..., min_length=10, max_length=10)
    time: str = Field(..., min_length=4, max_length=5)
    text: str = Field(..., min_length=2, max_length=240)
    target_type: Optional[str] = Field(None, max_length=40)
    target_id: Optional[str] = Field(None, max_length=120)


class UpdateCourseModuleData(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=120)
    task_date: Optional[str] = Field(None, min_length=10, max_length=10)


class PlannerCommandData(BaseModel):
    command: str = Field(..., min_length=3, max_length=600)
