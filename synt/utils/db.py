# -*- coding: utf-8 -*-
"""Functions to interact with databases."""
import os
import sqlite3
import redis
import cPickle as pickle
from synt import settings
from nltk.probability import ConditionalFreqDist
from nltk.metrics import BigramAssocMeasures
from synt.utils.text import sanitize_text
from synt.utils.processing import batch_job

def db_init(create=True):
    """Initializes the sqlite3 database."""
    if not os.path.exists(os.path.expanduser('~/.synt')):
        os.makedirs(os.path.expanduser('~/.synt/'))

    if not os.path.exists(settings.DB_FILE):
        conn = sqlite3.connect(settings.DB_FILE)
        cursor = conn.cursor()
        if create:
            cursor.execute('''CREATE TABLE item (id integer primary key, text text unique, sentiment text)''')
    else:
        conn = sqlite3.connect(settings.DB_FILE)
    return conn


def redis_feature_consumer(samples):
    """
    Stores counts to redis via a pipeline.
    """
    
    m = RedisManager()
   
    pipeline = m.r.pipeline()

    neg_processed, pos_processed = 0, 0

    for text, label in samples:
        
        count_label = label + '_wordcounts'

        tokens = sanitize_text(text)

        if tokens:
            if label.startswith('pos'):
                pos_processed += 1
            else:
                neg_processed += 1

            for word in set(tokens):
                pipeline.zincrby(count_label, word)

    pipeline.set('negative_processed', neg_processed) 
    pipeline.set('positive_processed', pos_processed)
    
    pipeline.execute()


class RedisManager(object):

    def __init__(self, db=5, host='localhost', purge=False):
        
        self.r = redis.Redis(db=db, host=host)
        if purge: self.r.flushdb()


    def store_freqdists(self):
        """
        Store features with counts to Redis.
        """

        label_word_freqdist = ConditionalFreqDist()

        pos_words = self.r.zrange('positive_wordcounts', 0, -1, withscores=True, desc=True)
        neg_words = self.r.zrange('negative_wordcounts', 0, -1, withscores=True, desc=True)

        assert pos_words and neg_words, 'Requires wordcounts to be stored in redis.'

        #build a condtional freqdist with the feature counts per label
        for word, count in pos_words:
            label_word_freqdist['positive'][word] = count

        for word,count in neg_words:
            label_word_freqdist['negative'][word] = count

        self.pickle_store('label_fd', label_word_freqdist)
        

    def store_feature_counts(self, samples, chunksize=10000, processes=None):
        """
        Stores word:count histograms for samples in Redis with the ability to increment.
        
        Keyword Arguments:
        wordcount_samples   -- the amount of samples to use for determining feature counts
        chunksize           -- the amount of samples to process at a time
        processes           -- the amount of processors to run in async
                               each process will be handed a chunksize of samples
                               i.e:
                               4 processes will be handed 10000 samples. If this is none 
                               it will be set to the default cpu count of your computer.
        """

        if 'positive_wordcounts' in self.r.keys():
            return
        
        def producer(offset, length):
            if offset + length > samples:
                length = samples - offset
            if length < 1:
                return []
            return get_samples(length, offset=offset)
                
        batch_job(producer, redis_feature_consumer, chunksize)
        
    def store_feature_scores(self):
        """
        Stores 'word scores' into Redis.
        """
        
        try:
            label_word_freqdist = self.pickle_load('label_fd')
        except TypeError:
            print('Requires frequency distributions to be built.')

        word_scores = {}

        pos_word_count = label_word_freqdist['positive'].N()
        neg_word_count = label_word_freqdist['negative'].N()
        total_word_count = pos_word_count + neg_word_count

        for label in label_word_freqdist.conditions():

            for word, freq in label_word_freqdist[label].iteritems():

                pos_score = BigramAssocMeasures.chi_sq(label_word_freqdist['positive'][word], (freq, pos_word_count), total_word_count)
                neg_score = BigramAssocMeasures.chi_sq(label_word_freqdist['negative'][word], (freq, neg_word_count), total_word_count)
            
                word_scores[word] = pos_score + neg_score 
      
        self.pickle_store('word_scores', word_scores)


    def pickle_store(self, name, data):
        self.r.set(name, pickle.dumps(data))

    def pickle_load(self, name):
        return pickle.loads(self.r.get(name))

    def store_classifier(self, name, classifier):
        """
        Stores a pickled a classifier into Redis.
        """
        self.pickle_store(name, classifier)

    def load_classifier(self, name):
        """
        Loads (unpickles) a classifier from Redis.
        """
        try:
            return self.pickle_load(name)    
        except TypeError:
            return     

    def get_top_words(self, label, start=0, end=10):
        """Return the top words for label from Redis store."""
        if self.r.exists(label):
            return self.r.zrange(label, start, end, withscores=True, desc=True) 

    def store_best_features(self, n=10000):
        """Store n best features to Redis."""
        if not n: return

        word_scores = self.pickle_load('word_scores')

        assert word_scores, "Word scores need to exist."
        
        best = sorted(word_scores.iteritems(), key=lambda (w,s): s, reverse=True)[:n]
        
        self.pickle_store('best_words',  best)
        
    def get_best_words(self, scores=False):
        """
        Return cached best_words

        If scores provided will return word/score tuple.
        """
        best_words = None
        if 'best_words' in self.r.keys():
            
            best_words =  pickle.load('best_words')

            if not scores:
                #in case of no scores we don't care about order
                tmp = {}
                for w in best_words:
                    tmp.setdefault(w[0], None)
                best_words = tmp 
                #best_words = [w[0] for w in best_words]

        return best_words


def get_sample_limit():
    """
    Returns the limit of samples so that both positive and negative samples
    will remain balanced.

    ex. if returned value is 203 we can be confident in drawing that many samples
    from both tables.
    """

    #this is an expensive operation in case of a large database
    #therefore we store the limit in redis and use that when we can
    man = RedisManager()
    if 'limit' in man.r.keys():
        return int(man.r.get('limit'))

    db = db_init()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM item where sentiment = 'positive'")
    pos_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM item where sentiment = 'negative'")
    neg_count = cursor.fetchone()[0]
    if neg_count > pos_count:
        limit = pos_count
    else:
        limit = neg_count
    
    #store to redis
    man.r.set('limit', limit)
    
    return limit

def get_samples(limit=get_sample_limit(), offset=0):
    """
    Returns a combined list of negative and positive samples.
    """

    db = db_init()
    cursor = db.cursor()

    sql =  "SELECT text, sentiment FROM item WHERE sentiment = ? LIMIT ? OFFSET ?"

    if limit < 2: limit = 2

    if limit > get_sample_limit():
        limit = get_sample_limit()

    if not limit % 2 == 0:
        limit -= 1 #we want an even number
    
    limit = limit / 2 
    offset = offset / 2

    cursor.execute(sql, ["negative", limit, offset])
    neg_samples = cursor.fetchall()

    cursor.execute(sql, ["positive", limit, offset])
    pos_samples = cursor.fetchall()

    return pos_samples + neg_samples

