import modal
import openai
openai.api_key = ""
def download_whisper():
  # Load the Whisper model
  import os
  import whisper
  print ("Download the Whisper model")

  # Perform download only once and save to Container storage
  whisper._download(whisper._MODELS["medium"], '/content/podcast/', False)


stub = modal.Stub("corise-podcast-project")
corise_image = modal.Image.debian_slim().pip_install("feedparser",
                                                     "https://github.com/openai/whisper/archive/9f70a352f9f8630ab3aa0d06af5cb9532bd8c21d.tar.gz",
                                                     "requests",
                                                     "ffmpeg",
                                                     "openai",
                                                     "tiktoken",
                                                     "wikipedia",
                                                     "ffmpeg-python").apt_install("ffmpeg").run_function(download_whisper)

@stub.function(image=corise_image, gpu="any", timeout=600)
def get_transcribe_podcast(rss_url, local_path):
  print ("Starting Podcast Transcription Function")
  print ("Feed URL: ", rss_url)
  print ("Local Path:", local_path)

  # Read from the RSS Feed URL
  import feedparser
  intelligence_feed = feedparser.parse(rss_url)
  podcast_title = intelligence_feed['feed']['title']
  episode_title = intelligence_feed.entries[0]['title']
  episode_image = intelligence_feed['feed']['image'].href
  for item in intelligence_feed.entries[0].links:
    if (item['type'] == 'audio/mpeg'):
      episode_url = item.href
  episode_name = "podcast_episode.mp3"
  print ("RSS URL read and episode URL: ", episode_url)

  # Download the podcast episode by parsing the RSS feed
  from pathlib import Path
  p = Path(local_path)
  p.mkdir(exist_ok=True)

  print ("Downloading the podcast episode")
  import requests
  with requests.get(episode_url, stream=True) as r:
    r.raise_for_status()
    episode_path = p.joinpath(episode_name)
    with open(episode_path, 'wb') as f:
      for chunk in r.iter_content(chunk_size=8192):
        f.write(chunk)

  print ("Podcast Episode downloaded")

  # Load the Whisper model
  import os
  import whisper

  # Load model from saved location
  print ("Load the Whisper model")
  model = whisper.load_model('medium', device='cuda', download_root='/content/podcast/')

  # Perform the transcription
  print ("Starting podcast transcription")
  result = model.transcribe(local_path + episode_name)

  # Return the transcribed text
  print ("Podcast transcription completed, returning results...")
  output = {}
  output['podcast_title'] = podcast_title
  output['episode_title'] = episode_title
  output['episode_image'] = episode_image
  output['episode_transcript'] = result['text']
  return output

@stub.function(image=corise_image, secret=modal.Secret.from_name("my-openai-secret"))
def get_podcast_summary(podcast_transcript):
  import openai
  instructPrompt = """
Using your vast knowledge base, please provide a concise summary of this podcast. Ensure the summary captures the main points, key findings, and opinions presented, while maintaining a neutral and objective tone.
"""

  request = instructPrompt + podcast_transcript

  chatOutput = openai.ChatCompletion.create(model="gpt-3.5-turbo-16k",
                                            messages=[{"role": "system", "content": "You are a helpful assistant."},
                                                      {"role": "user", "content": request}
                                                      ]
                                            )

  podcastSummary = chatOutput.choices[0].message.content
  return podcastSummary

@stub.function(image=corise_image, secret=modal.Secret.from_name("my-openai-secret"))
def get_podcast_guest(podcast_transcript):
  import openai
  import wikipedia
  import json

  completion = openai.ChatCompletion.create(
      model="gpt-3.5-turbo",
      messages=[{"role": "user", "content": podcast_transcript[:10000]}],
      functions=[
      {
          "name": "get_podcast_guest_information",
          "description": "Get information on the podcast guest using their full name and the name of the organization they are part of to search for them on Wikipedia",
          "parameters": {
              "type": "object",
              "properties": {
                  "guest_name": {
                      "type": "string",
                      "description": "The full name of the guest who is speaking in the podcast",
                  },
                  "guest_organization": {
                      "type": "string",
                      "description": "The full name of the organization that the podcast guest belongs to.",
                  },
                  "guest_title": {
                      "type": "string",
                      "description": "The title, designation, or role of the podcast guest in their organization",
                  },
              },
              "required": ["guest_name"],
          },
      }
  ],
  function_call={"name": "get_podcast_guest_information"}
  )
  podcast_guest = ""
  podcast_guest_org = ""
  podcast_guest_title = ""
  response_message = completion["choices"][0]["message"]
  if response_message.get("function_call"):
    function_name = response_message["function_call"]["name"]
    function_args = json.loads(response_message["function_call"]["arguments"])
    podcast_guest=function_args.get("guest_name")
    podcast_guest_org=function_args.get("guest_organization")
    podcast_guest_title=function_args.get("guest_title")

  if (podcast_guest is not None):
    if (podcast_guest_org is None):
      podcast_guest_org = ""
    if (podcast_guest_title is None):
      podcast_guest_title = ""
    try:
      input = wikipedia.page(podcast_guest + " " + podcast_guest_org + " " + podcast_guest_title, auto_suggest=True)
      podcast_guest_summary = input.summary
    except wikipedia.exceptions.PageError:
      print(f'Wikipedia page for guest "{podcast_guest} does not exist"')
      podcast_guest_summary = "Not Available"
    except wikipedia.exceptions.DisambiguationError as e:
      print(f'Ambiguous page request.  Possible matches are:')
      print(e.options)
      podcast_guest_summary = "Not Available"
  else:
    podcast_guest = "Not Available"
    podcast_guest_org = "Not Available"
    podcast_guest_title = "Not Available"
    podcast_guest_summary = "Not Available"

  podcastGuest = {}
  podcastGuest['name'] = podcast_guest
  podcastGuest['org'] = podcast_guest_org
  podcastGuest['title'] = podcast_guest_title
  podcastGuest['summary'] = podcast_guest_summary

  return podcastGuest

@stub.function(image=corise_image, secret=modal.Secret.from_name("my-openai-secret"))
def get_podcast_highlights(podcast_transcript):
  import openai
  instructPrompt = """
Based on the content of the latest episode of this podcast, please extract and present the key moments and highlights from the conversation. Focus on:

Insightful Comments: Any particularly enlightening or unexpected insights shared by the guest.
Critical Questions: Important questions posed by the host that led to deep or revealing answers.
Hot Topics: Sections of the conversation where a trending or controversial topic was discussed in-depth.
Noteworthy Opinions: Any strong or unique opinions expressed by either the guest or the host during the episode.
Please present these moments in a succinct and engaging manner, ensuring the essence of the conversation is captured.
"""

  request = instructPrompt + podcast_transcript

  chatOutput = openai.ChatCompletion.create(model="gpt-3.5-turbo-16k",
                                            messages=[{"role": "system", "content": "You are a helpful assistant."},
                                                      {"role": "user", "content": request}
                                                      ]
                                            )

  podcastHighlights = chatOutput.choices[0].message.content

  return podcastHighlights

@stub.function(image=corise_image, secret=modal.Secret.from_name("my-openai-secret"), timeout=1200)
def process_podcast(url, path):
  output = {}
  podcast_details = get_transcribe_podcast.call(url, path)
  podcast_summary = get_podcast_summary.call(podcast_details['episode_transcript'])
  podcast_guest = get_podcast_guest.call(podcast_details['episode_transcript'])
  podcast_highlights = get_podcast_highlights.call(podcast_details['episode_transcript'])
  output['podcast_details'] = podcast_details
  output['podcast_summary'] = podcast_summary
  output['podcast_guest'] = podcast_guest
  output['podcast_highlights'] = podcast_highlights
  return output

@stub.local_entrypoint()
def test_method(url, path):
  output = {}
  podcast_details = get_transcribe_podcast.call(url, path)
  print ("Podcast Summary: ", get_podcast_summary.call(podcast_details['episode_transcript']))
  print ("Podcast Guest Information: ", get_podcast_guest.call(podcast_details['episode_transcript']))
  print ("Podcast Highlights: ", get_podcast_highlights.call(podcast_details['episode_transcript']))
