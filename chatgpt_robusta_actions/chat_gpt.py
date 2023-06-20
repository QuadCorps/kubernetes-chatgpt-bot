import logging
import time

import cachetools
import openai
from openai.openai_object import OpenAIObject
from robusta.api import *

cache_size = 100
lru_cache = cachetools.LRUCache(maxsize=cache_size)
class AzureOpenAIAuthParams(ActionParams):
    """
    :var api_base: Azure OpenAI base url
    :var api_version: Azure OpenAI AI version
    :var api_key: Azure OpenAI API Key
    :var deployment_name: Azure OpenAI Deployment name
    """
    api_base: str
    api_version: str = "2023-05-15"
    api_key: str
    deployment_name: str

class AzureOpenAIParams(AzureOpenAIAuthParams):
    """
    :var search_term: Azure OpenAI search term
    """
    search_term: str

@action
def show_chat_gpt_search(event: ExecutionBaseEvent, params: AzureOpenAIParams):
    """
    Add a finding with ChatGPT top results for the specified search term.
    This action can be used together with the stack_overflow_enricher.
    """
    openai.api_type = "azure"
    openai.api_base = params.api_base
    openai.api_version = params.api_version
    openai.api_key = params.api_key

    logging.info(f"Azure OpenAI search term: {params.search_term}")

    answers = []
    try:
        if params.search_term in lru_cache:
            answers = lru_cache[params.search_term]
        else:
            start_time = time.time()
            input = [
                {"role": "system", "content": "You are a helpful assistant that helps Software Developers and DevOps Engineers to solve issues relating to Prometheus alerts for Kubernetes clusters. You are factual, clear and concise. Your responses are formatted using Slack specific markdown to ensure compatibility with displaying your response in a Slack message"},
                {"role": "user", "content": f"Here are the rules for Slack specific markdown, make sure to only use the following syntax in your responses : Text formatted in bold	Surround text with asterisks: '*your text*', '**' is invalid syntax so do not use it. Text formatted in italics, surround text with underscores: '_your text_'. Text formatted in strikethrough, surround text with tildes: '~your text~'. Text formatted in code, surround text with backticks: '`your text`'. Text formatted in blockquote, add an angled bracket in front of text: '>your text'. Text formatted in code block, add three backticks in front of text: '```your text'. Text formatted in an ordered list, add 1 and a full stop '1.' in front of text. Text formatted in a bulleted list, add an asterisk in front of text: '* your text'."},
                {"role": "user", "content": f"When responding, you use Slack specific markdown following the rules provided. Always bold and italic headings, i.e '*_The heading:_*', to clearly seperate the content with headers. Don't include any conversational response before the facts."},
                {"role": "user", "content": f"Please describe what the Kubernetes Prometheus alert '{params.search_term}' means, giving succinct examples of common causes. Provide any possible solutions including any troubleshooting steps that can be performed, give a real world example of a situation that can cause the alert can occur. Clearly seperate sections for Alert Name, Description, Real World Example, Common Causes, Troubleshooting Steps and Possible Solutions."},
            ]

            logging.info(f"Azure OpenAI input: {input}")
            res: OpenAIObject = openai.ChatCompletion.create(
                engine=params.deployment_name,
                messages=input
            )
            if res:
                logging.info(f"Azure OpenAI response: {res}")
                total_tokens = res.usage['total_tokens']
                time_taken = time.time() - start_time
                response_content = res.choices[0].message.content
                lru_cache[params.search_term] = [response_content]  # Store only the main response in the cache
                answers.append(response_content)

            answers.append(f"\n\n ---")
            answers.append(f"\n\n | Time taken: {time_taken:.2f} seconds | Total tokens used: {total_tokens} |")

    except Exception as e:
        answers.append(f"Error calling ChatCompletion.create: {e}")
        raise

    finding = Finding(
        title=f"Azure OpenAI ({params.model}) Results",
        source=FindingSource.PROMETHEUS,
        aggregation_key="Azure OpenAI Wisdom",
    )

    if answers:
        finding.add_enrichment([MarkdownBlock('\n'.join(answers))])
    else:
        finding.add_enrichment(
            [
                MarkdownBlock(
                    f'Sorry, Azure OpenAI doesn\'t know anything about "{params.search_term}"'
                )
            ]
        )
    event.add_finding(finding)

@action
def chat_gpt_enricher(alert: PrometheusKubernetesAlert, params: AzureOpenAIAuthParams):
    """
    Add a button to the alert - clicking it will ask chat gpt to help find a solution.
    """
    alert_name = alert.alert.labels.get("alertname", "")
    if not alert_name:
        return

    alert.add_enrichment(
        [
            CallbackBlock(
                {
                    f'Ask Azure OpenAI: {alert_name}': CallbackChoice(
                        action=show_chat_gpt_search,
                        action_params=AzureOpenAIParams(
                            search_term=f"{alert_name}",
                            api_base=params.api_base,
                            api_version=params.api_version,
                            api_key=params.api_key,
                            deployment_name=params.deployment_name
                        ),
                    )
                },
            )
        ]
    )
