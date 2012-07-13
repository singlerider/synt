# -*- coding: utf-8 -*-
#Config for the synt project

import os
import nltk

#Where collected databases and user config are stored by default
SYNT_PATH = os.path.expanduser("~/.synt")
USER_CONFIG_PATH = os.path.join(SYNT_PATH, 'config.py')

#Emoticons may serve as useful indicatiors in classifying sentiment.
#These are the set of default emoticons to use, you may use your own or
#disregard emoticons entirely they are optional.
EMOTICONS = [
    ':-L', ':L', '<3', '8)', '8-)', '8-}', '8]', '8-]', '8-|', '8(', '8-(',
    '8-[', '8-{', '-.-', 'xx', '</3', ':-{', ': )', ': (', ';]', ':{', '={',
    ':-}', ':}', '=}', ':)', ';)', ':/', '=/', ';/', 'x(', 'x)', ':D', 'T_T',
    'O.o', 'o.o', 'o_O', 'o.-', 'O.-', '-.o', '-.O', 'X_X', 'x_x', 'XD', 'DX',
    ':-$', ':|', '-_-', 'D:', ':-)', '^_^', '=)', '=]', '=|', '=[', '=(', ':(',
    ':-(', ':, (', ':\'(', ':-]', ':-[', ':]', ':[', '>.>', '<.<'
]


#Default classifiers supported
CLASSIFIERS = {
    'naivebayes'   : nltk.NaiveBayesClassifier,
}

#The database that will house the classifer data.
REDIS_DB = 5

#The database used for tests.
REDIS_TEST_DB = 10

REDIS_HOST = 'localhost'

REDIS_PASSWORD = None

#If the user config is in place, use settings from there instead.
if os.path.exists(USER_CONFIG_PATH):
    execfile(USER_CONFIG_PATH)
