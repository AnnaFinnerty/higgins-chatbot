# HIGGINS V1
# Supported features: 
## Lambda Integration
## Custom Scripts

import boto3
import os
from dotenv import load_dotenv
import sys
import json
import logging
import random
import re
from collections import namedtuple
from pathlib import Path
import time
from pprint import pprint

#load environment variables if you are using lambda functions locally
load_dotenv()
lambda_client = boto3.client(service_name='lambda')

# Fix Python2/Python3 incompatibility
try: input = raw_input
except NameError: pass

# logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger(__name__)

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

    def load(self, path):
        self.loadfile(path)
        basepath = Path('scripts/')
        files_in_basepath = basepath.iterdir()
        print(type(files_in_basepath))
        for item in files_in_basepath:
            if item.is_file():
                print(item.name)
                self.loadfile('scripts/'+item.name)

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
        for decomp in key.decomps:
            results = self._match_decomp(decomp.parts, words)
            if results is None:
                log.debug('Decomp did not match: %s', decomp.parts)
                continue
            log.debug('Decomp matched: %s', decomp.parts)
            log.debug('Decomp results: %s', results)
            results = [self._sub(words, self.posts) for words in results]
            log.debug('Decomp results after posts: %s', results)
            reasmb = self._next_reasmb(decomp)
            log.debug('Using reassembly: %s', reasmb)

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

    def respond(self, text):
        if text.lower() in self.quits:
            return None
        
        # phrases = re.split('[.,?;]', text)
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

        #keys are turned lowercase here, which may be a problem for entity recognition
        keys = [self.keys[w.lower()] for w in words if w.lower() in self.keys]
        keys = sorted(keys, key=lambda k: -k.weight)
        log.debug('Sorted keys: %s', [(k.word, k.weight) for k in keys])

        output = None

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
                output = self._next_reasmb(self.keys['xnone'].decomps[0])
                log.debug('Output from xnone: %s', output)

        return " ".join(output)

    def initial(self):
        return random.choice(self.initials)

    def final(self):
        return random.choice(self.finals)

    def invoke_lambda(self,l):
        arn = os.environ.get(l)
        response = lambda_client.invoke(
            FunctionName=str(arn),
            InvocationType="RequestResponse"
        )
        payload = json.loads(response['Payload'].read())
        return payload['body']

    def run(self):
        print(self.initial())
        while True:
            sent = input('> ')
            output = self.respond(sent)
            if output is None:
                break

            print(output)

        print(self.final())

def main():
    higgins = Higgins()
    higgins.load('scripts/core/script.txt')
    higgins.run()

if __name__ == '__main__':
    logging.basicConfig()
    main()
else:
    higgins = Higgins()
    higgins.load('scripts/core/script.txt')


def lambda_handler(event, context):
    # TODO implement
    output = higgins.respond(event['Payload'])
    return {
        'statusCode': 200,
        'body': output
    }