# HIGGINS V2
# Supported features: 
## Sentiment Analysis 
## Entity Detection, Reaction, Short Term Memory
## Lambda Integration
## Custom Scripts

import boto3
import os
import sys
import json
import logging
import random
import re
from collections import namedtuple
from pathlib import Path
import time
from pprint import pprint


# Fix Python2/Python3 incompatibility
try: input = raw_input
except NameError: pass

# logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger(__name__)
log.propagate = False

#CONFIG
#load environment variables

bucket = os.environ.get('bucket_name')
load_s3 = True
s3_client = boto3.resource('s3')

#enable lambda functions
lambda_client = boto3.client(service_name='lambda')

#advanced detection settings
detect_entities_enabled = True
detect_sentiment_enabled = True
comprehend_client = boto3.client(service_name='comprehend', region_name='us-east-1')

class Key:
    def __init__(self, word, weight, decomps):
        self.word = word
        self.weight = weight
        self.decomps = decomps


class Decomp:
    def __init__(self, parts, save, reasmbs):
        self.parts = parts
        self.save = save
        self.reasmbs = reasmbs
        self.next_reasmb_index = 0

class Higgins:
    def __init__(self):
        self.initials = []
        self.finals = []
        self.follows = []
        self.quits = []
        self.lambdas = []
        self.pres = {}
        self.posts = {}
        self.synons = {}
        self.keys = {}
        self.stm = []
        self.mtm = {}
        self.last_key = None
        self.simple = False
        self.minDelay = 100
        self.maxDelay = 200
        self.delay = 10

    def loadfile(self, path):
        key = None
        decomp = None
        with open(path) as file:
            for line in file:
                if not line.strip():
                    continue
                tag, content = [part.strip() for part in line.split(':')]
                if tag == 'initial':
                    self.initials.append(content)
                elif tag == 'final':
                    self.finals.append(content)
                elif tag == 'follow':
                    self.follows.append(content)
                elif tag == 'lambda':
                    self.lambdas.append(content)
                elif tag == 'quit':
                    self.quits.append(content)
                elif tag == 'pre':
                    parts = content.split(' ')
                    self.pres[parts[0]] = parts[1:]
                elif tag == 'post':
                    parts = content.split(' ')
                    self.posts[parts[0]] = parts[1:]
                elif tag == 'synon':
                    parts = content.split(' ')
                    self.synons[parts[0]] = parts
                elif tag == 'key':
                    parts = content.split(' ')
                    word = parts[0]
                    weight = int(parts[1]) if len(parts) > 1 else 1
                    key = Key(word, weight, [])
                    self.keys[word] = key
                elif tag == 'decomp':
                    parts = content.split(' ')
                    save = False
                    if parts[0] == '$':
                        save = True
                        parts = parts[1:]
                    decomp = Decomp(parts, save, [])
                    key.decomps.append(decomp)
                elif tag == 'reasmb':
                    parts = content.split(' ')
                    decomp.reasmbs.append(parts)

    def loads3file(self, file):
        key = None
        decomp = None
        for line in file.get()['Body']._raw_stream:
            line = str(line.decode('ascii'))
            if len(line.split(':')) == 2:
                tag, content = [part.strip() for part in line.split(':')]
                if tag == 'initial':
                    self.initials.append(content)
                elif tag == 'final':
                    self.finals.append(content)
                elif tag == 'follow':
                    self.follows.append(content)
                elif tag == 'lambda':
                    self.lambdas.append(content)
                elif tag == 'quit':
                    self.quits.append(content)
                elif tag == 'pre':
                    parts = content.split(' ')
                    self.pres[parts[0]] = parts[1:]
                elif tag == 'post':
                    parts = content.split(' ')
                    self.posts[parts[0]] = parts[1:]
                elif tag == 'synon':
                    parts = content.split(' ')
                    self.synons[parts[0]] = parts
                elif tag == 'key':
                    parts = content.split(' ')
                    word = parts[0]
                    weight = int(parts[1]) if len(parts) > 1 else 1
                    key = Key(word, weight, [])
                    self.keys[word] = key
                elif tag == 'decomp':
                    parts = content.split(' ')
                    save = False
                    if parts[0] == '$':
                        save = True
                        parts = parts[1:]
                    decomp = Decomp(parts, save, [])
                    key.decomps.append(decomp)
                elif tag == 'reasmb':
                    parts = content.split(' ')
                    decomp.reasmbs.append(parts)

    #loads all scripts in local scripts folder
    def load_local(self):
        print('loading local')
        corepath = Path('scripts/core/')
        files_in_corepath = corepath.iterdir()
        for item in files_in_corepath:
            if item.is_file():
                self.loadfile(item)
        addonpath = Path('scripts/addons/')
        files_in_addonpath = addonpath.iterdir()
        for item in files_in_addonpath:
            if item.is_file():
                self.loadfile(item)

    #loads s3 scripts
    def load_s3(self):
        print('loading s3')
        obj = s3_client.Object(bucket, 'script.txt')
        self.loads3file(obj)
        my_bucket = s3_client.Bucket(bucket)
        for object_summary in my_bucket.objects.filter(Prefix="scripts/core/"):
            print(object_summary.key)
            obj = s3_client.Object(bucket, object_summary.key)
            print(obj)
            self.loads3file(obj)
        

    def _match_decomp_r(self, parts, words, results):
        if not parts and not words:
            return True
        if not parts or (not words and parts != ['*']):
            return False
        if parts[0] == '*':
            for index in range(len(words), -1, -1):
                results.append(words[:index])
                if self._match_decomp_r(parts[1:], words[index:], results):
                    return True
                results.pop()
            return False
        elif parts[0].startswith('@'):
            root = parts[0][1:]
            if not root in self.synons:
                raise ValueError("Unknown synonym root {}".format(root))
            if not words[0].lower() in self.synons[root]:
                return False
            results.append([words[0]])
            return self._match_decomp_r(parts[1:], words[1:], results)
        elif parts[0].lower() != words[0].lower():
            return False
        else:
            return self._match_decomp_r(parts[1:], words[1:], results)

    def _match_decomp(self, parts, words):
        results = []
        if self._match_decomp_r(parts, words, results):
            return results
        return None

    def _next_reasmb(self, decomp):
        index = decomp.next_reasmb_index
        result = decomp.reasmbs[index % len(decomp.reasmbs)]
        decomp.next_reasmb_index = index + 1
        return result

    def _reassemble(self, reasmb, results):
        output = []
        for reword in reasmb:
            if not reword:
                continue
            if reword[0] == '(' and reword[-1] == ')':
                index = int(reword[1:-1])
                if index < 1 or index > len(results):
                    raise ValueError("Invalid result index {}".format(index))
                insert = results[index - 1]
                for punct in [',', '.', ';']:
                    if punct in insert:
                        insert = insert[:insert.index(punct)]
                output.extend(insert)
            else:
                output.append(reword)
        return output

    def _sub(self, words, sub):
        output = []
        for word in words:
            word_lower = word.lower()
            if word_lower in sub:
                output.extend(sub[word_lower])
            else:
                output.append(word)
        return output

    def _match_key(self, words, key):
        print(key)
        print(words)
        for decomp in key.decomps:
            print(decomp.parts)
            results = self._match_decomp(decomp.parts, words)
            print(results)
            if results is None:
                log.debug('Decomp did not match: %s', decomp.parts)
                continue
            log.debug('Decomp matched: %s', decomp.parts)
            log.debug('Decomp results: %s', results)
            results = [self._sub(words, self.posts) for words in results]
            log.debug('Decomp results after posts: %s', results)
            reasmb = self._next_reasmb(decomp)
            log.debug('Using reassembly: %s', reasmb)

            # other keys can be added here!
            if reasmb[0] == 'goto':
                goto_key = reasmb[1]
                if not goto_key in self.keys:
                    raise ValueError("Invalid goto key {}".format(goto_key))
                log.debug('Goto key: %s', goto_key)
                return self._match_key(words, self.keys[goto_key])
            elif reasmb[0] == 'lambda':
                print("let's run a lambda!")
                lambda_name = reasmb[1]
                result = self.invoke_lambda(lambda_name)
                return result
            # keys that link to custom scripts/actions can be added down here!
            elif reasmb[0] == 'confirm':
                print("we're going to need some confirmation here")
                print("but what are we confirming?")
            output = self._reassemble(reasmb, results)
            if decomp.save:
                self.stm.append(output)
                log.debug('Saved to memory: %s', output)
                continue
            return output
        return None
    
    def invoke_lambda(self,l):
        arn = os.environ.get(l)
        response = lambda_client.invoke(
            FunctionName=str(arn),
            InvocationType="RequestResponse"
        )
        payload = json.loads(response['Payload'].read())
        return payload['body']

    def entity_detection(self,text):
        entities = comprehend_client.detect_entities(Text=text, LanguageCode='en')
        for e in entities['Entities']:
            print(e)
            output = None
            
            if e['Text'].lower() in self.keys:
                key = self.keys[e['Text'].lower()]
                words = [w for w in text.split(' ') if w]
                words = self._sub(words, self.pres)
                output = self._match_key(words, key)
                self.stm.append(output)
                return output
            elif e['Type'].lower() in self.keys:
                key = self.keys[e['Type'].lower()]
                words = [w for w in text.split(' ') if w]
                words = self._sub(words, self.pres)
                if e['Text'] in self.mtm:
                    print('in mtm')
                    print(e['Text'])
                else:
                    self.mtm[e['Text']] = []
                    self.mtm[e['Text']].append(output)
                    print(self.mtm)
                output = self._match_key(words, key)
                self.stm.append(output)
                return output
        return None
    
    def sentiment_detection(self,text):
        output = None
        raw = comprehend_client.detect_sentiment(Text=text, LanguageCode='en')
        s = raw['Sentiment']
        if s.lower() in self.keys:
            key = self.keys[s.lower()]
            words = [w for w in text.split(' ') if w]
            words = self._sub(words, self.pres)
            output = self._match_key(words, key)
            return output
        return None

    def respond(self, text):
        output = None

        if detect_entities_enabled:
            entity_output = self.entity_detection(text)
            if entity_output is not None:
                return " ".join(entity_output)

        if text.lower() in self.quits:
            return None

        phrases = re.split('[.,?;]', text)
        # print(phrases)

        text = re.sub(r'\s*\.+\s*', ' . ', text)
        text = re.sub(r'\s*,+\s*', ' , ', text)
        text = re.sub(r'\s*\.+\s*', ' ? ', text)
        text = re.sub(r'\s*;+\s*', ' ; ', text)
        log.debug('After punctuation cleanup: %s', text)

        words = [w for w in text.split(' ') if w]
        log.debug('Input: %s', words)

        words = self._sub(words, self.pres)
        log.debug('After pre-substitution: %s', words)

        keys = [self.keys[w.lower()] for w in words if w.lower() in self.keys]
        keys = sorted(keys, key=lambda k: -k.weight)
        log.debug('Sorted keys: %s', [(k.word, k.weight) for k in keys])
 
        for key in keys:
            log.debug('key:')
            # pprint(key.__dict__)
            output = self._match_key(words, key)
            if output:
                last_key = key
                log.debug('Output from key: %s', output)
                break
        if not output:
            #if no output, pull default from stm
            if self.stm:
                index = random.randrange(len(self.stm))
                output = self.stm.pop(index)
                log.debug('Output from memory: %s', output)
            else:
                if detect_sentiment_enabled:
                    sentiment_response = self.sentiment_detection(text)
                    if sentiment_response is not None:
                        output = sentiment_response
                else:
                    # fallback output
                    output = self._next_reasmb(self.keys['xnone'].decomps[0])
                    log.debug('Output from xnone: %s', output)

        return " ".join(output)

    def initial(self):
        return random.choice(self.initials)

    def final(self):
        return random.choice(self.finals)

    def run(self):
        print(self.initial())

        while True:
            sent = input('> ')
            output = self.respond(sent)
            if output is None:
                break

            print(output)

        print(self.final())

#local only methods
def main():
    higgins = Higgins()
    higgins.load_local()
    # higgins.load_s3()
    higgins.run()

if __name__ == '__main__':
    load_dotenv()
    logging.basicConfig()
    main()
else:
    higgins = Higgins()
    higgins.load_s3()


def lambda_handler(event, context):
    # TODO implement
    output = higgins.respond(event['Payload'])
    return {
        'statusCode': 200,
        'body': output
    }