"""
Gestión ética de mensajes directos.
Solo responde a conversaciones iniciadas por el usuario (inbound-first).
NUNCA envía mensajes masivos no solicitados.
"""

from datetime import datetime

from core.config import settings
from core.database import get_session
from core.logger import get_logger
from core.models import DMConversation, DMMessage, Platform
from engagement.response_generator import generate_dm_response

log = get_logger(__name__)


class DMManager:

    def register_inbound_message(
        self,
        platform: Platform,
        thread_id: str,
        contact_username: str,
        message_text: str,
        sent_at: datetime | None = None,
    ) -> DMConversation:
        """
        Registra un mensaje entrante.
        El hecho de que el usuario haya escrito = consentimiento implícito.
        """
        with get_session() as db:
            conv = db.query(DMConversation).filter_by(thread_id=thread_id).first()

            if not conv:
                conv = DMConversation(
                    platform=platform,
                    thread_id=thread_id,
                    contact_username=contact_username,
                    consent_given=True,   # el usuario inició la conversación
                    lead_status="new",
                    created_at=datetime.utcnow(),
                )
                db.add(conv)
                db.flush()
                log.info("Nueva conversación DM de @%s", contact_username)

            msg = DMMessage(
                conversation_id=conv.id,
                direction="inbound",
                text=message_text,
                sent_at=sent_at or datetime.utcnow(),
                ai_generated=False,
                approved=True,
            )
            db.add(msg)
            conv.last_message_at = datetime.utcnow()
            db.commit()
            db.refresh(conv)
            return conv

    def generate_reply(
        self, conversation_id: int, auto_approve: bool = False
    ) -> dict:
        """Genera una respuesta al último mensaje de una conversación."""
        with get_session() as db:
            conv = db.get(DMConversation, conversation_id)
            if not conv:
                raise ValueError(f"Conversación {conversation_id} no encontrada")
            if not conv.consent_given:
                raise PermissionError(
                    "No se puede responder: el usuario no ha dado consentimiento."
                )

            messages = (
                db.query(DMMessage)
                .filter_by(conversation_id=conversation_id)
                .order_by(DMMessage.sent_at.desc())
                .limit(10)
                .all()
            )
            last_inbound = next(
                (m for m in messages if m.direction == "inbound"), None
            )
            if not last_inbound:
                raise ValueError("No hay mensajes entrantes en esta conversación")

            # Construir resumen de contexto
            context = self._build_context(messages)

            response_text = generate_dm_response(
                thread_id=conv.thread_id,
                last_message=last_inbound.text,
                context_summary=context,
            )

            reply_msg = DMMessage(
                conversation_id=conversation_id,
                direction="outbound",
                text=response_text,
                sent_at=None,   # aún no enviado
                ai_generated=True,
                approved=auto_approve,
            )
            db.add(reply_msg)
            db.commit()
            db.refresh(reply_msg)

            return {
                "message_id": reply_msg.id,
                "text": response_text,
                "approved": auto_approve,
                "conversation_id": conversation_id,
            }

    def approve_and_send(self, message_id: int) -> bool:
        """Aprueba y envía un mensaje DM generado por IA."""
        with get_session() as db:
            msg = db.get(DMMessage, message_id)
            if not msg or msg.direction != "outbound":
                return False

            conv = db.get(DMConversation, msg.conversation_id)

            # Aquí iría la llamada a la API de la plataforma
            success = self._send_via_platform(conv, msg.text)

            if success:
                msg.approved = True
                msg.sent_at = datetime.utcnow()
                conv.last_message_at = datetime.utcnow()
                # Actualizar estado de lead si aplica
                if conv.lead_status == "new":
                    conv.lead_status = "warm"
            db.commit()
            return success

    def update_context_summary(self, conversation_id: int) -> str:
        """Actualiza el resumen de contexto de la conversación con LLM."""
        from core.llm import llm
        with get_session() as db:
            conv = db.get(DMConversation, conversation_id)
            messages = (
                db.query(DMMessage)
                .filter_by(conversation_id=conversation_id)
                .order_by(DMMessage.sent_at.asc())
                .all()
            )
            transcript = "\n".join(
                f"{'Usuario' if m.direction == 'inbound' else settings.BRAND_NAME}: {m.text}"
                for m in messages
            )
            prompt = f"""
Resume esta conversación en 2-3 oraciones para dar contexto futuro:

{transcript}

Incluye: tema principal, tono del usuario, posible intención de compra/interés.
"""
            summary = llm.generate(prompt).strip()
            conv.context_summary = summary
            db.commit()
            return summary

    def _build_context(self, messages: list[DMMessage]) -> str:
        lines = []
        for m in reversed(messages[-6:]):  # últimos 6 mensajes
            who = "Usuario" if m.direction == "inbound" else settings.BRAND_NAME
            lines.append(f"{who}: {m.text}")
        return "\n".join(lines)

    def _send_via_platform(self, conv: DMConversation, text: str) -> bool:
        # Placeholder: implementar según plataforma
        # Instagram: Graph API Messages (requiere aprobación Meta)
        # TikTok: TikTok Business API
        log.info(
            "[SIMULADO] Enviando DM a @%s en %s: '%s'",
            conv.contact_username,
            conv.platform,
            text[:60],
        )
        return True   # cambiar a False si la API falla


dm_manager = DMManager()
