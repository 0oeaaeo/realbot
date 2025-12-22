import io
import base64
from PIL import Image
import discord
import httpx

MAX_MESSAGE_LIMIT = 100

async def gather_context(message, limit: int, user_list: list | None = None):
    """
    Gathers context from the last 'limit' messages in the channel, capped at MAX_MESSAGE_LIMIT.
    Returns the message string and a map of users found in the context.
    """
    # Cap the limit to the maximum allowed
    actual_limit = min(limit, MAX_MESSAGE_LIMIT)
    
    messages = []
    async for msg in message.channel.history(limit=actual_limit):
        messages.append(msg)
    messages.reverse()

    user_map = {}
    message_context_string = "\n---\nMessage History:\n"
    for msg in messages:
        line = f"{msg.author.name}: {msg.content}\n"
        message_context_string += line
        if msg.author.id not in user_map:
            user_map[msg.author.id] = msg.author.name
    
    context_parts = [{"role": "user", "parts": [{"text": message_context_string}]}]
    return context_parts, user_map



async def gather_user_avatar(message, user_ids: list):
    """
    Gathers and processes avatars for a list of user IDs using their avatar URL.
    Returns a list of dictionaries with image data for tool processing.
    """
    avatar_data_list = []
    async with httpx.AsyncClient() as client:
        for user_id in user_ids:
            try:
                user_id = int(user_id)
                # Use discord.utils.get on the guild's members list
                target_user = discord.utils.get(message.guild.members, id=user_id)
                if not target_user:
                    print(f"Could not find user with ID {user_id} in this guild.")
                    continue
            except (ValueError) as e:
                print(f"Invalid user ID format {user_id}: {e}")
                continue

            if not target_user.avatar:
                print(f"User {target_user.name} does not have an avatar.")
                continue

            try:
                avatar_url = target_user.avatar.url
                response = await client.get(str(avatar_url))
                response.raise_for_status()
                avatar_bytes = response.content
                
                img = Image.open(io.BytesIO(avatar_bytes))
                mime_type = f'image/{img.format.lower() if img.format else "jpeg"}'

                if getattr(img, 'is_animated', False):
                    img.seek(0)
                    output_buffer = io.BytesIO()
                    img.convert('RGB').save(output_buffer, format='JPEG')
                    avatar_bytes = output_buffer.getvalue()
                    mime_type = 'image/jpeg'
                
                encoded_avatar = base64.b64encode(avatar_bytes).decode('utf-8')
                avatar_data_list.append({
                    "username": target_user.name,
                    "user_id": str(target_user.id),
                    "mime_type": mime_type,
                    "data": encoded_avatar
                })
            except Exception as e:
                print(f"Could not process avatar for {target_user.name}: {e}")
            
    return avatar_data_list


