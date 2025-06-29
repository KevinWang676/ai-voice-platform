import json
import re
from datetime import datetime
from flask import session
from flask_login import current_user
from openai import OpenAI
from volcenginesdkarkruntime import Ark
from backend.config import Config
from backend.utils import (
    format_response_text, 
    handle_api_error, 
    get_chat_history_key, 
    clear_all_chat_histories,
    replace_quotes_and_dashes,
    italicize_parentheses
)

# Lazy initialization of Doubao client
_doubao_client = None

def get_doubao_client():
    """Get the Doubao client, initializing it if necessary"""
    global _doubao_client
    if _doubao_client is None:
        _doubao_client = Ark(
            api_key=Config.DOUBAO_API_KEY,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
    return _doubao_client

# For backward compatibility, provide doubao_client as a property
class DoubaoClientProxy:
    @property
    def chat(self):
        return get_doubao_client().chat

doubao_client = DoubaoClientProxy()

# Lazy initialization of Kimi client
_kimi_client = None

def get_kimi_client():
    """Get the Kimi client, initializing it if necessary"""
    global _kimi_client
    if _kimi_client is None:
        _kimi_client = OpenAI(
            base_url="https://api.moonshot.cn/v1",
            api_key=Config.KIMI_API_KEY
        )
    return _kimi_client

# For backward compatibility, provide kimi_client as a property  
class KimiClientProxy:
    @property
    def chat(self):
        return get_kimi_client().chat

kimi_client = KimiClientProxy()

def make_kimi_request(query):
    """Make a web search request to Kimi API"""
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        clear_all_chat_histories(user_id)
        session['chat_history'] = []
        session['new_ending_history'] = []
        session.modified = True

        messages = [
            {
                "role": "system",
                "content": "You are a professional and diligent plot summary assistant, capable of using web search functionality to carefully search for and summarize detailed plots and character introductions of novels or movies. For each user request, please first search using the web search tool, then accurately summarize the plot and main character information based on the web search results."
            },
            {
                "role": "user",
                "content": f"1. Please diligently search and introduce the detailed plot and ending of the work '{query}', prioritizing the novel if available. 2. Describe the plot development as meticulously as possible, accurately detailing the beginning, development, climax, and ending. Note: The ending part must be particularly detailed and accurate, including specific details. 3. Please provide a very detailed introduction to the most important protagonists, accurately describing their background, personality, experiences, preferences, ending, and the precise relationships between them. 4. Please do not mention any content unrelated to the plot or protagonists."
            }
        ]

        print("Sending request to Kimi API with messages:", json.dumps(messages, ensure_ascii=False))

        try:
            finish_reason = None
            while finish_reason is None or finish_reason == "tool_calls":
                completion = kimi_client.chat.completions.create(
                    model="moonshot-v1-32k",
                    messages=messages,
                    temperature=0.3,
                    max_tokens=8192,
                    tools=[{
                        "type": "builtin_function",
                        "function": {
                            "name": "$web_search"
                        }
                    }],
                    stream=False
                )

                choice = completion.choices[0]
                finish_reason = choice.finish_reason

                if finish_reason == "tool_calls":
                    messages.append(choice.message)
                    for tool_call in choice.message.tool_calls:
                        tool_call_arguments = json.loads(tool_call.function.arguments)

                        # For web search, we just return the arguments
                        tool_result = tool_call_arguments

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": json.dumps(tool_result)
                        })
                else:
                    # If we have content, format and return it
                    if choice.message.content and len(choice.message.content.strip()) > 0:
                        formatted_content = format_response_text(choice.message.content)
                        return formatted_content, None

            return None, "Could not find relevant story information."

        except Exception as api_error:
            error_message = handle_api_error(api_error)
            print(f"API Error: {str(api_error)}")
            return None, error_message

    except Exception as e:
        print("Error in make_kimi_request:", str(e))
        return None, f"An error occurred during request processing: {str(e)}"

def make_kimi_character_request(query):
    """
    Make a web search request to Kimi API for character search

    Args:
        query (str): The character name to search for
    """
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        clear_all_chat_histories(user_id)
        session['chat_history'] = []
        session['new_ending_history'] = []
        session.modified = True

        messages = [
            {
                "role": "system",
                "content": "You are a professional role-playing settings assistant, capable of using web search functionality to collect and organize detailed setting information for characters. Whether it's a fictional character or a real-life celebrity, you can provide rich, consistent, and playable character settings. You will cite reliable sources and clearly distinguish between facts and inferences. Your goal is to provide information detailed enough to accurately mimic the character's language style, thought process, and behavior patterns."
            },
            {
                "role": "user",
                "content": f"Please search for information about '{query}' and organize it into detailed settings suitable for a role-playing task.\n\n"
                        f"If it's a fictional character:\n"
                        f"1. Basic Character Information: Detailed description of age, identity, appearance, way of speaking.\n"
                        f"2. Personality Traits: Detailed analysis of personality characteristics and worldview.\n"
                        f"3. Important Relationships: Detailed description of key interactions and relationships with other important characters.\n"
                        f"4. Character Development: Detailed description of the character's background and growth trajectory.\n"
                        f"5. Classic Scene: Detailed description of one of the most important scenes the character participated in, serving as the environment for the role-playing task.\n"
                        f"6. Classic Dialogue Examples: 3-5 dialogue snippets from the original work that reflect the character's traits, serving as a reference for tone.\n\n"
                        f"If it's a real person:\n"
                        f"1. Public Image: Professional identity, age, notable achievements, and publicly perceived image characteristics.\n"
                        f"2. Expression Style: Language style in public settings, common topics, and ways of expression.\n"
                        f"3. Area of Expertise: Field of expertise, important works, and professional knowledge background.\n"
                        f"4. Public Stance: Views, values, and interests expressed in public.\n"
                        f"5. Public Interaction: Interaction patterns with the public, media, or other public figures.\n"
                        f"6. Representative Quotes: 3-5 public statements that reflect the person's characteristics, serving as a reference for tone.\n\n"
            }
        ]

        print("Sending request to Kimi API with messages:", json.dumps(messages, ensure_ascii=False))

        try:
            finish_reason = None
            while finish_reason is None or finish_reason == "tool_calls":
                completion = kimi_client.chat.completions.create(
                    model="moonshot-v1-32k",
                    messages=messages,
                    temperature=0.3,
                    max_tokens=8192,
                    tools=[{
                        "type": "builtin_function",
                        "function": {
                            "name": "$web_search"
                        }
                    }],
                    stream=False
                )

                choice = completion.choices[0]
                finish_reason = choice.finish_reason

                if finish_reason == "tool_calls":
                    messages.append(choice.message)
                    for tool_call in choice.message.tool_calls:
                        tool_call_arguments = json.loads(tool_call.function.arguments)
                        tool_result = tool_call_arguments
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": json.dumps(tool_result)
                        })
                else:
                    if choice.message.content and len(choice.message.content.strip()) > 0:
                        formatted_content = format_response_text(choice.message.content)
                        return formatted_content, None

            return None, "Could not find relevant character information."

        except Exception as api_error:
            error_message = handle_api_error(api_error)
            print(f"API Error: {str(api_error)}")
            return None, error_message

    except Exception as e:
        print("Error in make_kimi_character_request:", str(e))
        return None, f"An error occurred during request processing: {str(e)}"

def generate_new_ending(history_key, story_content, user_prompt):
    """Generate new ending with session-based chat history"""
    try:
        # Get chat history from session
        chat_history = session.get('new_ending_history', [])

        # Create system prompt
        system_prompt = {
            "role": "system",
            "content": f"""You are a creative and excellent novelist and screenwriter, highly skilled at crafting new endings based on the story's plot development and user requirements. You need to follow these principles to create a compelling new ending:

1. Ensure the new ending completely aligns with the story's internal logic and character personalities.
2. Satisfy the user's desired ending direction while adhering to the story's logical development; avoid contradictions.
3. Use beautiful and evocative literary language to capture the reader's interest.
4. The new ending should be as detailed and rich as possible, including descriptions of details, psychology, environment, etc.
5. Strictly follow the user's desired ending direction without any deviation.
6. If the user provides new requirements, actively cooperate and fulfill them diligently.

Remember: Your goal is to create a brilliant ending that both meets the user's expectations and fits the story's own logic, satisfying the user's request. If the user's instructions are unclear, analyze their historical requests to understand their true needs.

Please carefully read the following story content and protagonist introduction: {story_content}
"""
        }


        full_prompt = f"""

User's desired ending direction or instructions:
{user_prompt}

Now please begin writing the new ending or responding to the user's instructions directly, without any additional explanation."""
        # Prepare messages for API call
        messages = [system_prompt] + chat_history + [{"role": "user", "content": full_prompt}]

        try:
            completion = doubao_client.chat.completions.create(
                model="ep-20250222031319-fvlbj",
                messages=messages,
                temperature=0.8,  # Slightly increased for more creativity
                max_tokens=4096,
                stream=False
            )

            response_content = completion.choices[0].message.content

            # Update the chat history
            # with the user prompt and assistant response
            chat_history.append({"role": "user", "content": full_prompt})
            chat_history.append({"role": "assistant", "content": response_content})

            # Store the updated chat history back in the session
            session['new_ending_history'] = chat_history
            session.modified = True


            if response_content:
                if len(response_content.strip()) > 0:
                    return response_content, None

            return None, "Sorry! There was a problem generating the ending. Please try again."

        except Exception as api_error:
            error_message = handle_api_error(api_error)
            print(f"API Error in generate_new_ending: {str(api_error)}")
            return None, error_message

    except Exception as e:
        print("Error in generate_new_ending:", str(e))
        return None, str(e)

def character_chat(history_key, model_type, story_content, character_name, message):
    """Handle character chat with session-based chat history"""
    try:
        # Get chat history from session
        chat_history = session.get('chat_history', [])

        # Create system prompt
        system_prompt = {
            "role": "system",
            "content": f"""You are now going to role-play as the character specified by the user. Please follow these rules:
1. Base your responses entirely on the character's personality and manner of speaking from the work or game setting.
2. Maintain consistency and coherence in the character's dialogue; it needs to be realistic and natural.
3. Ensure your answers align with the character's personality traits, background setting, and the plot or game's setting and logic.
4. Use the character's tone and way of speaking to converse naturally with the user.
5. If the user's question goes beyond the scope of the story content, respond reasonably based on the character's personality.
6. Include descriptions of actions, thoughts, environment, and details in your responses, enclosed entirely in parentheses, and address the user in the second person ("you").
7. In the dialogue, use names and titles for each character that are consistent with the relationships defined in the plot.
8. If the user's setting contradicts the original plot, prioritize the user's instructions and settings, fulfilling their requests.

The character's introduction is as follows, pay special attention to the descriptions of background, personality, experiences, and relationships:
{story_content}

The user's instruction and setting for you is: {character_name}
Please carefully follow the user's instructions and setting, and converse with the user."""
        }

        # Prepare messages for API call
        messages = [system_prompt] + chat_history + [{"role": "user", "content": message}]

        try:
            if model_type == "deepseek":
                completion = doubao_client.chat.completions.create(
                    model="ep-20250208045440-ljsn9",
                    messages=messages,
                    temperature=0.8
                )
                chat_content = completion.choices[0].message.content

                # Process the chat content to replace quotes and dash sequences.
                chat_content = replace_quotes_and_dashes(chat_content)
                chat_content = italicize_parentheses(chat_content)

                response_content = (
                    '<div>' + chat_content + '</div>'
                )

                actual_ai_response = completion.choices[0].message.content

            else:
                completion = doubao_client.chat.completions.create(
                    model="ep-20250222031319-fvlbj",
                    messages=messages,
                    temperature=0.8
                )
                response_content = italicize_parentheses(completion.choices[0].message.content)

                actual_ai_response = completion.choices[0].message.content

            if response_content:
                return response_content, None, actual_ai_response

        except Exception as api_error:
            error_message = handle_api_error(api_error)
            print(f"API Error in character_chat: {str(api_error)}")
            return None, error_message, None

    except Exception as e:
        print("Error in character_chat:", str(e))
        return None, str(e), None

def character_chat_new(db, CharacterChat, character_name, story_content, message):
    """
    Handle character chat with database-stored chat history

    Args:
        character_name (str): The name of the character to chat with
        story_content (str): The character's background and information
        message (str): User's message

    Returns:
        tuple: (response_content, error_message, actual_ai_response)
    """
    try:
        if not current_user.is_authenticated:
            return None, "Please log in to chat with characters", None

        # Find existing chat history from database or create new
        chat_record = CharacterChat.query.filter_by(
            user_id=current_user.id,
            character_name=character_name
        ).first()

        if chat_record:
            # Use existing chat history
            chat_history = json.loads(chat_record.chat_history)
            # Update the character description if it has changed
            if chat_record.character_description != story_content:
                chat_record.character_description = story_content
        else:
            # Create new chat history
            chat_history = []
            chat_record = CharacterChat(
                user_id=current_user.id,
                character_name=character_name,
                chat_history=json.dumps([]),
                character_description=story_content
            )
            db.session.add(chat_record)

        # Create system prompt
        system_prompt = {
            "role": "system",
            "content": f"""You are now going to role-play as the character specified by the user. Please follow these rules:
1. Base your responses entirely on the character's personality and manner of speaking from the work or game setting.
2. Maintain consistency and coherence in the character's dialogue; it needs to be realistic and natural.
3. Ensure your answers align with the character's personality traits, background setting, and the plot or game's setting and logic.
4. Use the character's tone and way of speaking to converse naturally with the user.
5. If the user's question goes beyond the scope of the story content, respond reasonably based on the character's personality.
6. Include descriptions of actions and thoughts in your responses, enclosed in parentheses.
7. In the dialogue, use names and titles for each character that are consistent with the relationships defined in the plot.
8. If the user's setting contradicts the original plot, prioritize the user's instructions and settings, fulfilling their requests.

The character's introduction is as follows, pay special attention to the descriptions of background, personality, experiences, and relationships:
{story_content}

Please carefully follow the character's setting and converse with the user."""
        }

        # Prepare messages for API call
        messages = [system_prompt] + chat_history + [{"role": "user", "content": message}]

        completion = doubao_client.chat.completions.create(
            model="ep-20250324135816-8zzzm",
            messages=messages,
            temperature=0.8,
            max_tokens=8192
        )

        response_content = italicize_parentheses(completion.choices[0].message.content)
        actual_ai_response = completion.choices[0].message.content

        # Add new messages to chat history
        chat_history.append({"role": "user", "content": message})
        chat_history.append({"role": "assistant", "content": actual_ai_response})

        # Save updated chat history to database
        chat_record.chat_history = json.dumps(chat_history)
        chat_record.updated_at = datetime.utcnow()
        db.session.commit()

        if response_content:
            return response_content, None, actual_ai_response
        return None, "Failed to generate response", None

    except Exception as e:
        print("Error in character_chat_new:", str(e))
        return None, str(e), None 