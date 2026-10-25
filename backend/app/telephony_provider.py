"""Twilio's official SDK boundary for inbound browser voice, signed callbacks and call control."""

from urllib.parse import urlparse

from fastapi import HTTPException, Request
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

from .config import settings
from .models import User


def public_url(path: str) -> str:
    """Use a configured canonical URL, never untrusted forwarded host headers, for signatures and callbacks."""
    base = settings.telephony_public_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise HTTPException(503, "Set TELEPHONY_PUBLIC_URL to the public HTTPS backend origin.")
    return base + path


def require_telephony() -> None:
    """Fail closed until the server-side inbound calling integration is configured."""
    if not settings.telephony_enabled or not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise HTTPException(503, "Live phone calling is not configured.")
    public_url("")


def browser_identity(user: User) -> str:
    """Derive a provider-safe dispatcher identity from the authenticated database identity."""
    return "kontrol_" + user.id.replace("-", "")


def browser_token(user: User) -> str:
    """Issue a short-lived incoming-only Voice grant; never expose Twilio or OpenAI API secrets."""
    require_telephony()
    if not settings.twilio_api_key_sid or not settings.twilio_api_key_secret:
        raise HTTPException(503, "Configure the Twilio API key for browser calling.")
    token = AccessToken(settings.twilio_account_sid, settings.twilio_api_key_sid,
                        settings.twilio_api_key_secret, identity=browser_identity(user), ttl=600)
    token.add_grant(VoiceGrant(incoming_allow=True))
    return token.to_jwt()


async def verified_form(request: Request) -> dict[str, str]:
    """Validate every provider callback using Twilio's official validator and the exact public URL."""
    require_telephony()
    if int(request.headers.get("content-length", "0")) > 65536:
        raise HTTPException(413, "Callback too large")
    form = await request.form(max_fields=80)
    signature = request.headers.get("x-twilio-signature", "")
    if not RequestValidator(settings.twilio_auth_token).validate(public_url(request.url.path), form, signature):
        raise HTTPException(403, "Invalid provider signature")
    data = {key: str(value) for key, value in form.items()}
    if data.get("AccountSid") != settings.twilio_account_sid:
        raise HTTPException(403, "Invalid provider account")
    return data


def incoming_twiml(call_id: str, identities: list[str]) -> str:
    """Fork both media tracks for transcription while Twilio bridges actual browser/caller audio."""
    response = VoiceResponse()
    start = response.start()
    start.stream(url=public_url(f"/telephony/media/{call_id}").replace("https://", "wss://", 1),
                 track="both_tracks")
    options = {"answer_on_bridge": True, "timeout": 45,
               "action": public_url(f"/telephony/ended/{call_id}"), "method": "POST"}
    if settings.twilio_record_calls:
        options.update(record="record-from-answer-dual",
                       recording_status_callback=public_url(f"/telephony/recording/{call_id}"))
    dial = response.dial(**options)
    for identity in identities:
        client = dial.client(status_callback=public_url(f"/telephony/status/{call_id}"),
                             status_callback_event="initiated ringing answered completed")
        client.identity(identity)
        client.parameter(name="KontrolCallId", value=call_id)
    response.hangup()
    return str(response)


def hang_up(provider_sid: str) -> None:
    """End the actual provider call; keep provider errors and credentials out of API output."""
    try:
        Client(settings.twilio_account_sid, settings.twilio_auth_token).calls(provider_sid).update(status="completed")
    except Exception:
        raise HTTPException(502, "Provider could not end the call. Retry or use the phone controls.") from None
