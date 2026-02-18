from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.schemas import (
    AccountSettingsData,
    LoginData,
    RefreshTokenData,
    SignupData,
    UpdatePasswordData,
    UpdateProfileData,
)
from app.helpers import (
    build_offline_auth_response,
    get_account_settings_from_metadata,
    is_ssl_or_network_auth_error,
)
from main import (
    OFFLINE_AUTH_FALLBACK,
    SUPABASE_AVAILABLE,
    get_current_user,
    logger,
    supabase,
)

router = APIRouter()

@router.post("/api/login")
async def login(data: LoginData):
    """User login endpoint"""
    if not SUPABASE_AVAILABLE or not supabase:
        if OFFLINE_AUTH_FALLBACK:
            logger.warning("Supabase unavailable; offline fallback login granted.")
            return build_offline_auth_response(data.username, data.email, mode="logged_in")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Supabase is unavailable. Enable OFFLINE_AUTH_FALLBACK for guest mode."}
        )
    try:
        result = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })

        if result.user:
            logger.info(f"User logged in: {result.user.id}")
            return {
                "status": "logged_in",
                "user_id": result.user.id,
                "email": result.user.email,
                "display_name": result.user.user_metadata.get("display_name", data.username),
                "access_token": result.session.access_token,
                "refresh_token": result.session.refresh_token
            }

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid credentials"}
        )
    except Exception as e:
        logger.error(f"Login error: {e}")
        if OFFLINE_AUTH_FALLBACK and is_ssl_or_network_auth_error(e):
            logger.warning("Login Supabase SSL/network issue; offline fallback login granted.")
            return build_offline_auth_response(data.username, data.email, mode="logged_in")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid credentials"}
        )


@router.post("/api/signup")
async def signup(data: SignupData):
    """User signup endpoint"""
    if not SUPABASE_AVAILABLE or not supabase:
        if OFFLINE_AUTH_FALLBACK:
            logger.warning("Supabase unavailable; offline fallback signup granted.")
            return build_offline_auth_response(data.username, data.email, mode="signed_up")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Supabase is unavailable. Signup is temporarily disabled."}
        )
    try:
        result = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
            "options": {
                "data": {"display_name": data.username}
            }
        })

        if result.user:
            logger.info(f"New user signed up: {result.user.id}")
            return {
                "status": "signed_up",
                "user_id": result.user.id,
                "email": result.user.email,
                "display_name": result.user.user_metadata.get("display_name", data.username),
                "access_token": result.session.access_token,
                "refresh_token": result.session.refresh_token
            }

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Signup failed"}
        )
    except Exception as e:
        logger.error(f"Signup error: {e}")
        if OFFLINE_AUTH_FALLBACK and is_ssl_or_network_auth_error(e):
            logger.warning("Signup Supabase SSL/network issue; offline fallback signup granted.")
            return build_offline_auth_response(data.username, data.email, mode="signed_up")
        error_msg = str(e)
        if "already registered" in error_msg.lower():
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Email already registered"}
            )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Signup failed. Please try again."}
        )


@router.post("/api/update-profile")
async def update_profile(
        data: UpdateProfileData,
        current_user=Depends(get_current_user)
):
    """Update user profile"""
    try:
        result = supabase.auth.update_user({
            "data": {"display_name": data.display_name}
        })

        if result and result.user:
            logger.info(f"Profile updated for user: {current_user.id}")
            return {"success": True, "display_name": data.display_name}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update profile"}
        )
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update profile. Please try again."}
        )


@router.post("/api/account-settings")
async def update_account_settings(
        data: AccountSettingsData,
        current_user=Depends(get_current_user)
):
    """Update persisted account settings in user metadata"""
    try:
        user_metadata = current_user.user_metadata or {}
        merged_metadata = {
            **user_metadata,
            "account_settings": {
                "web_search_enabled": data.web_search_enabled,
                "save_chat_history": data.save_chat_history,
                "study_reminders_enabled": data.study_reminders_enabled,
                "grade_level": (data.grade_level or "").strip(),
                "education_board": (data.education_board or "").strip(),
            }
        }

        result = supabase.auth.update_user({"data": merged_metadata})
        if result and result.user:
            logger.info(f"Account settings updated for user: {current_user.id}")
            return {"success": True, "account_settings": merged_metadata["account_settings"]}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update account settings"}
        )
    except Exception as e:
        logger.error(f"Account settings update error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update account settings. Please try again."}
        )


@router.post("/api/change-password")
async def change_password(
        data: UpdatePasswordData,
        current_user=Depends(get_current_user)
):
    """Change account password for authenticated user"""
    try:
        result = supabase.auth.update_user({"password": data.new_password})
        if result and result.user:
            logger.info(f"Password updated for user: {current_user.id}")
            return {"success": True}

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update password"}
        )
    except Exception as e:
        logger.error(f"Password update error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Failed to update password. Please try again."}
        )


@router.post("/api/refresh")
async def refresh_access_token(data: RefreshTokenData):
    """Refresh access token using Supabase refresh token."""
    try:
        refreshed = supabase.auth.refresh_session(data.refresh_token)
        session = refreshed.session
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to refresh session"
            )
        return {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )


@router.get("/api/me")
async def get_me(current_user=Depends(get_current_user)):
    """Get current user information"""
    user_metadata = current_user.user_metadata or {}
    display_name = user_metadata.get("display_name", "User")
    if not display_name or display_name == "User":
        display_name = current_user.email.split('@')[0]
    account_settings = get_account_settings_from_metadata(user_metadata)

    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "display_name": display_name,
        "account_settings": account_settings
    }
