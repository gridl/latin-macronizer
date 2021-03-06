#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015 Johan Winge
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

MORPHEUSDIR = 'morpheus/'
RFTAGGERDIR = '/usr/local/bin/'
#USEMORPHEUSDATABASE = True
USEMORPHEUSDATABASE = False
DBNAME = 'macronizer'
DBUSER = 'theusername'
DBPASSWORD = 'thepassword'
DBHOST = 'localhost'

import psycopg2
from tempfile import mkstemp
import re
import sys
import os
import codecs
from itertools import izip
import postags

reload(sys)  
sys.setdefaultencoding('utf8')

def pairwise(iterable):
    "s -> (s0,s1), (s2,s3), (s4, s5), ..."
    a = iter(iterable)
    return izip(a, a)
#enddef
def toascii(txt):
    for source, replacement in [(u"æ","ae"),(u"Æ","Ae"),(u"œ","oe"),(u"Œ","Oe"),
                                (u"ä","a"),(u"ë","e"),(u"ï","i"),(u"ö","o"),(u"ü","u"),(u"ÿ","u")]:
        txt = txt.replace(source,replacement)
    return txt
#enddef
def touiorthography(txt):
    for source, replacement in [(u"v","u"),(u"U","V"),(u"j","i"),(u"J",u"I")]:
        txt = txt.replace(source,replacement)
    return txt
#enddef

class Wordlist():
    def __init__(self):
        if USEMORPHEUSDATABASE:
            try:
                self.dbconn = psycopg2.connect("dbname='%s' host='%s' user='%s' password='%s'" % (DBNAME, DBHOST, DBUSER, DBPASSWORD))
                self.dbcursor = self.dbconn.cursor()
            except:
                raise Exception("Error: Could not connect to the database.")
        self.unknownwords = set() # Unknown to Morpheus
        self.formtolemmas = {}
        self.formtoaccenteds = {}
        self.formtotaglemmaaccents = {}
        self.loadwordsfromfile("macrons.txt")
    #enddef
    def reinitializedatabase(self):
        if USEMORPHEUSDATABASE:
            self.dbcursor.execute("DROP TABLE IF EXISTS morpheus")
            self.dbcursor.execute("CREATE TABLE morpheus(id SERIAL PRIMARY KEY, wordform TEXT NOT NULL, morphtag TEXT, lemma TEXT, accented TEXT)")
            self.dbconn.commit()
    #enddef
    def loadwordsfromfile(self, filename):
        plaindbfile = codecs.open(filename, 'r', 'utf8')
        for line in plaindbfile:
            [wordform, morphtag, lemma, accented] = line.split()
            self.addwordparse(wordform, morphtag, lemma, accented)
    #enddef
    def loadwords(self, words): # Expects a set of lowercase words
        unseenwords = set()
        for word in words:
            if word in self.formtotaglemmaaccents: # Word is already loaded
                continue
            if not self.loadwordfromdb(word): # Could not find word in database
                unseenwords.add(word)
        if len(unseenwords) > 0:
            self.crunchwords(unseenwords) # Try to parse unseen words with Morpheus, and add result to the database
            for word in unseenwords:
                if not self.loadwordfromdb(word):
                    raise Exception("Error: Could not store "+word+" in the database.")
    #enddef
    def loadwordfromdb(self, word):
        if USEMORPHEUSDATABASE:
            try:
                self.dbcursor.execute("SELECT wordform, morphtag, lemma, accented FROM morpheus WHERE wordform = %s", (word, ))
            except:
                raise Exception("Error: Database table is missing. Please initialize the database.")
            #endtry
            rows = self.dbcursor.fetchall()
            if len(rows) == 0:
                return False
            for [wordform, morphtag, lemma, accented] in rows:
                self.addwordparse(wordform, morphtag, lemma, accented)
        else:
            self.addwordparse(word, None, None, None)
        return True
    #enddef
    def addwordparse(self, wordform, morphtag, lemma, accented):
        if accented == None:
            self.unknownwords.add(wordform)
        else:
            self.formtolemmas[wordform] = self.formtolemmas.get(wordform,[]) + [lemma]
            self.formtoaccenteds[wordform] = self.formtoaccenteds.get(wordform,[]) + [accented.lower()]
            self.formtotaglemmaaccents[wordform] = self.formtotaglemmaaccents.get(wordform,[]) + [(morphtag,lemma,accented)]
    #enddef
    def crunchwords(self, words):
        morphinpfd, morphinpfname = mkstemp()
        os.close(morphinpfd)
        crunchedfd, crunchedfname = mkstemp()
        os.close(crunchedfd)
        morphinpfile = codecs.open(morphinpfname, 'w', 'utf8')
        for word in words:
            morphinpfile.write(word.strip().lower()+'\n')
            morphinpfile.write(word.strip().capitalize()+'\n')
        morphinpfile.close()
        os.system("MORPHLIB="+MORPHEUSDIR+"stemlib "+MORPHEUSDIR+"bin/cruncher -L < "+morphinpfname+" > "+crunchedfname+" 2> /dev/null")
        os.remove(morphinpfname)
        with codecs.open(crunchedfname, 'r', 'utf8') as crunchedfile:
            morpheus = crunchedfile.read()
        os.remove(crunchedfname)
        crunchedwordforms = {}
        knownwords = set()
        for wordform, NLs in pairwise(morpheus.split("\n")):
            wordform = wordform.strip().lower()
            NLs = NLs.strip()
            crunchedwordforms[wordform] = crunchedwordforms.get(wordform,"") + NLs
        for wordform in crunchedwordforms:
            NLs = crunchedwordforms[wordform]
            parses = []
            for NL in NLs.split("<NL>"):
                NL = NL.replace("</NL>","")
                NLparts = NL.split()
                if len(NLparts) > 0:
                    parses += postags.Morpheus2Parses(wordform,NL)
            lemmatagtoaccenteds = {}
            for parse in parses:
                lemma = parse[postags.LEMMA].replace("#","").replace("1","").replace(" ","+")
                parse[postags.LEMMA] = lemma
                accented = parse[postags.ACCENTEDFORM]
                if parse[postags.LEMMA].startswith("trans-") and accented[3] != "_": # Work around shortcoming in Morpheus
                    accented = accented[:3] + "_" + accented[3:]
                if accented == "male_" or accented == "cave_":
                    accented = accented[:-1]
                if accented == "fame":
                    accented += "_"
                parse[postags.ACCENTEDFORM] = accented
                # Remove highly unlikely alternatives:
                if ( accented not in ["me_nse_", "fabuli_s", "vi_ri_", "vi_ro_", "vi_rum", "vi_ro_rum", "vi_ri_s", "vi_ro_s"] and
                     not (accented.startswith("vi_ct") and lemma == "vivo") and
                     not (accented.startswith("ori_") and lemma == "orior") and
                     not (accented.startswith("mori_") and lemma == "morior") and
                     not (accented.startswith("conci_") and lemma == "concitus") and
                     lemma not in ["pareas", "de_-escendo", "de_-eo", "de_-edo", "Nus", "progredio", "aris"] ):
                    tag = postags.Parse2LDT(parse)
                    lemmatagtoaccenteds[(lemma,tag)] = lemmatagtoaccenteds.get((lemma,tag),[]) + [accented]
            if len(lemmatagtoaccenteds) == 0:
                continue
            knownwords.add(wordform);
            for (lemma, tag), accenteds in lemmatagtoaccenteds.items():
                # Sometimes there are several different accented forms; prefer 'volvit' to 'voluit', 'Ju_lius' to 'Iu_lius' etc.
                bestaccented = sorted(accenteds, key = lambda x: x.count('v')+x.count('j')+x.count('J'))[-1]
                lemmatagtoaccenteds[(lemma, tag)] = bestaccented
            for (lemma, tag), accented in lemmatagtoaccenteds.items():
                self.dbcursor.execute("INSERT INTO morpheus (wordform, morphtag, lemma, accented) VALUES (%s,%s,%s,%s)", (wordform, tag, lemma, accented))
        ## The remaining were unknown to Morpheus:
        for wordform in words - knownwords:
            self.dbcursor.execute("INSERT INTO morpheus (wordform) VALUES (%s)", (wordform, ))
        ## Remove duplicates:
        self.dbcursor.execute("DELETE FROM morpheus USING morpheus m2 WHERE morpheus.wordform = m2.wordform AND (morpheus.morphtag = m2.morphtag OR morpheus.morphtag IS NULL AND m2.morphtag IS NULL) AND (morpheus.lemma = m2.lemma OR morpheus.lemma IS NULL AND m2.lemma IS NULL) AND (morpheus.accented = m2.accented OR morpheus.accented IS NULL AND m2.accented IS NULL) AND morpheus.id > m2.id")
        self.dbconn.commit()
    #enddef
#endclass

class Token:
    def __init__(self, token):
        self.tag = ""
        self.lemma = ""
        self.accented = ""
        self.macronized = ""
        self.token = postags.removemacrons(token)
        self.isword = re.match("[^\W\d_]", token, flags=re.UNICODE)
        self.isspace = re.match("\s", token, flags=re.UNICODE)
        self.isreordered = False
        self.startssentence = False
        self.endssentence = False
        self.isunknown = False
        self.isambiguous = False
    #enddef
    def split(self, pos, reorder):
        newtokena = Token(self.token[:-pos])
        newtokenb = Token(self.token[-pos:])
        newtokena.startssentence = self.startssentence
        if reorder:
            newtokenb.isreordered = True
            return [newtokenb, newtokena]
        else:
            return [newtokena, newtokenb]
    #enddef
    def show(self):
        print (self.token + "\t"  + self.tag + "\t" + self.lemma + "\t" + self.accented).expandtabs(16)
    #enddef
    def macronize(self, domacronize, alsomaius, performutov, performitoj):
        plain = self.token
        accented = self.accented
        if domacronize and alsomaius and 'j' in accented:
            if not accented.startswith(("bij", "fidej", "Foroj", "ju_rej", "multij", "praej", "quadrij", "rej", "retroj", "se_mij", "sesquij", "u_nij", "introj")):
                accented = re.sub('([aeiouy])(j[aeiouy])', r'\1_\2', accented)
        if not self.isword:
            self.macronized = plain
            return
        if (not domacronize or not "_" in accented) and not performutov and not performitoj:
            self.macronized = plain
            return
        if self.isreordered:
            self.macronized = plain
            if performutov and self.macronized.lower() == "ue":
                if self.macronized[0] == 'u':
                    self.macronized = 'v' + self.macronized[1]
                elif self.macronized[0] == 'U':
                    self.macronized = 'V' + self.macronized[1]
            return
        if plain == accented.replace("_",""):
            if domacronize:
                self.macronized = accented
                return
            else:
                self.macronized = plain
                return
        #endif
        def inscost(a):
            if a == '_':
                return 0
            return 2
        def subcost(p,a):
            if a == '_':
                return 100
            if (a in "IJij" and p in "IJij") or (a in "UVuv" and p in "UVuv"):
                return 1
            return 2
        def delcost(b):
            return 2
        #enddef
        n = len(plain) + 1
        m = len(accented) + 1
        distance = [[0 for i in range(m)] for j in range(n)]
        for i in range(1, n):
            distance[i][0] = distance[i-1][0] + delcost(plain[i-1])
        for j in range(1, m):
            distance[0][j] = distance[0][j-1] + inscost(accented[j-1])
        for i in range(1, n):
            for j in range(1, m):
                if toascii(plain[i-1].lower()) == toascii(accented[j-1].lower()):
                    distance[i][j] = distance[i-1][j-1]
                else:
                    rghtcost = distance[i-1][j] + delcost(plain[i-1])
                    diagcost = distance[i-1][j-1] + subcost(plain[i-1],accented[j-1])
                    downcost = distance[i][j-1] + inscost(accented[j-1])
                    distance[i][j] = min(rghtcost,diagcost,downcost)
        result = ""
        while i != 0 and j != 0:
            upcost = distance[i][j-1] if j > 0 else 1000
            diagcost = distance[i-1][j-1] if j > 0 and i > 0 else 1000
            leftcost = distance[i-1][j] if i > 0 else 1000
            if diagcost <= upcost and diagcost < leftcost: ## To-do: review the comparisons...
                i -= 1
                j -= 1
                if performutov and accented[j].lower() == 'v' and plain[i] == 'u':
                    result = 'v' + result
                elif performutov and accented[j].lower() == 'v' and plain[i] == 'U':
                    result = 'V' + result
                elif performitoj and accented[j].lower() == 'j' and plain[i] == 'i':
                    result = 'j' + result
                elif performitoj and accented[j].lower() == 'j' and plain[i] == 'I':
                    result = 'J' + result
                else:
                    result = plain[i] + result
            elif upcost <= diagcost and upcost <= leftcost:
                j -= 1
                if domacronize and accented[j] == '_':
                    result = "_" + result
            else:
                i -= 1
                result = plain[i] + result
        self.macronized = result
    #enddef
#endclass

class Tokenization:
    def __init__(self, text):
        self.tokens = []
        possiblesentenceend = False
        sentencehasended = True
        # This does not work?: [^\W\d_]+|\s+|([^\w\s]|[\d_])+
        for chunk in re.findall(u"[^\W\d_]+|\s+|[^\w\s]+|[\d_]+", text, re.UNICODE):
            token = Token(chunk)
            if token.isword:
                if sentencehasended:
                    token.startssentence = True
                sentencehasended = False
                possiblesentenceend = (len(token.token) > 1)
            elif possiblesentenceend and any(i in token.token for i in '.;:?!'):
                token.endssentence = True
                possiblesentenceend = False
                sentencehasended = True
            self.tokens.append(token)
    #enddef
    def allwordforms(self):
        words = set()
        for token in self.tokens:
            if token.isword:
                words.add(toascii(token.token).lower())
        return words
    #enddef
    dividenda = {"nequid":4, "attamen":5, "unusquisque":7, "unaquaeque":7, "unumquodque":7, "uniuscuiusque":8, "uniuscujusque":8,
                 "unicuique":6, "unumquemque":7, "unamquamque":7, "unoquoque":6, "unaquaque":6,
                 "cuiusmodi":4, "cujusmodi":4, "quojusmodi":4, "eiusmodi":4, "ejusmodi":4, "huiuscemodi":4, "hujuscemodi":4,
                 "huiusmodi":4, "hujusmodi":4, "istiusmodi":4, "nullomodo":4, "quodammodo":4,
                 "nudiustertius":7, "nonnisi":4, "plusquam":4, "proculdubio":5, "quamplures":6, "quamprimum":6,
                 "quinetiam":5, "uerumetiam":5, "verumetiam":5, "verumtamen":5, "uerumtamen":5,
                 "paterfamilias":8, "patrisfamilias":8, "patremfamilias":8, "patrifamilias":8, "patrefamilias":8, "patresfamilias":8,
                 "patrumfamilias":8, "patribusfamilias":8, "materfamilias":8, "matrisfamilias":8, "matremfamilias":8, "matrifamilias":8,
                 "matrefamilias":8, "matresfamilias":8, "matrumfamilias":8, "matribusfamilias":8,
                 "respublica":7, "reipublicae":8, "rempublicam":8, "senatusconsultum":9, "senatusconsulto":8, "senatusconsulti":8,
                 "usufructu":6, "usumfructum":7, "ususfructus":7, "supradicti":5, "supradictum":6, "supradictus":6, "supradicto":5,
                 "seipse":4, "seipsa":4, "seipsum":5, "seipsam":5, "seipso":4, "seipsos":5, "seipsas":5, "seipsis":5,
                 "semetipse":4, "semetipsa":4, "semetipsum":5, "semetipsam":5, "semetipso":4, "semetipsos":5, "semetipsas":5, "semetipsis":5,
                 "teipsum":5, "temetipsum":5, "vosmetipsos":5, "idipsum":5}
                 #satisdare, satisdetur, etc
    def splittokens(self, wordlist):
        newwords = set()
        newtokens = []
        for oldtoken in self.tokens:
            tobeadded = []
            oldlc = oldtoken.token.lower()
            if oldtoken.isword and oldlc != "que" and (oldlc in wordlist.unknownwords or oldlc in ["nec","neque","necnon","seque","seseque","quique","secumque"]):
                if oldlc == "nec":
                    tobeadded = oldtoken.split(1,True)
                elif oldlc == "necnon":
                    [tempa,tempb] = oldtoken.split(3,False)
                    tobeadded = tempa.split(1,True) + [tempb]
                elif oldlc in Tokenization.dividenda:
                    tobeadded = oldtoken.split(Tokenization.dividenda[oldlc],False)                 
                elif len(oldlc) > 3 and oldlc.endswith("que"):
                    tobeadded = oldtoken.split(3,True)
                elif len(oldlc) > 2 and oldlc.endswith(("ve","ue","ne")):
                    tobeadded = oldtoken.split(2,True)
            #endif
            if len(tobeadded) == 0:
                newtokens.append(oldtoken)
            else:
                for part in tobeadded:
                    newwords.add(toascii(part.token).lower())
                    newtokens.append(part)
        self.tokens = newtokens
        return newwords
    #enddef
    def show(self):
        for token in self.tokens[:500]:
            if token.isword:
                token.show()
            if token.endssentence:
                print
        if len(self.tokens) > 500:
            print "... (truncated) ..."
    #enddef
    def addtags(self):
        totaggerfd, totaggerfname = mkstemp()
        os.close(totaggerfd)
        fromtaggerfd, fromtaggerfname = mkstemp()
        os.close(fromtaggerfd)
        totaggerfile = codecs.open(totaggerfname, 'w', 'utf8')
        for token in self.tokens:
            if not token.isspace:
                totaggerfile.write(toascii(token.token))
                totaggerfile.write("\n")         
            if token.endssentence:
                totaggerfile.write("\n")         
        totaggerfile.close()
        os.system(RFTAGGERDIR+"rft-annotate -s -q rftagger-ldt.model "+totaggerfname+" "+fromtaggerfname)
        fromtaggerfile = codecs.open(fromtaggerfname, 'r', 'utf8')
        for token in self.tokens:
            if not token.isspace:
                try:
                    (taggedtoken,tag) = fromtaggerfile.readline().strip().split("\t")
                    assert toascii(token.token) == taggedtoken
                except:
                    raise Exception("Error: Something went wrong with the tagging.")
                #endtry
                token.tag = tag.replace(".","")
            if token.endssentence:
               fromtaggerfile.readline()
        fromtaggerfile.close()
        os.remove(totaggerfname)
        os.remove(fromtaggerfname)
    #enddef
    def addlemmas(self, wordlist):
        lemmafrequency = {}
        wordlemmafreq = {}
        wordformtolemmasintrain = {}
        train = codecs.open('ldt-corpus.txt', 'r', 'utf8')
        for line in train:
            if '\t' in line:
                [wordform, tag, lemma] = line.strip().split('\t')
                lemmafrequency[lemma] = lemmafrequency.get(lemma,0) + 1
                wordlemmafreq[(wordform,lemma)] = wordlemmafreq.get((wordform,lemma),0) + 1
                wordformtolemmasintrain[wordform] =  wordformtolemmasintrain.get(wordform,set()) | set([lemma])
        for token in self.tokens:
            wordform = toascii(token.token)
            bestlemma = "-"
            if wordform in wordformtolemmasintrain:
                bestlemma = ""
                maxfreq = 0
                for trainlemma in wordformtolemmasintrain[wordform]:
                    if wordlemmafreq[(wordform,trainlemma)] > maxfreq:
                        maxfreq = wordlemmafreq[(wordform,trainlemma)]
                        bestlemma = trainlemma
            elif wordform.lower() in wordlist.formtolemmas:
                bestlemma = ""
                maxfreq = -1
                for lexlemma in wordlist.formtolemmas[wordform.lower()]:
                    if lemmafrequency.get(lexlemma,0) > maxfreq:
                        maxfreq = lemmafrequency.get(lexlemma,0)
                        bestlemma = lexlemma
            #endif
            token.lemma = bestlemma
    #enddef
    def getaccents(self, wordlist):
        def levenshtein(s1, s2):
            if len(s1) < len(s2):
                return levenshtein(s2, s1)
            if len(s2) == 0:
                return len(s1)
            previous_row = range(len(s2) + 1)
            for i, c1 in enumerate(s1):
                current_row = [i + 1]
                for j, c2 in enumerate(s2):
                    insertions = previous_row[j + 1] + 1
                    deletions = current_row[j] + 1
                    substitutions = previous_row[j] + (c1 != c2)
                    current_row.append(min(insertions, deletions, substitutions))
                previous_row = current_row
            return previous_row[-1]
        #enddef
        tagtoendings = {}
        endingsfile = codecs.open("macronized-endings.txt","r","utf8")
        for line in endingsfile:
            line = line.strip().split("\t")
            endingpairs = []
            for ending in line[1:]:
                endingpairs.append((ending, ending.replace("_","")))
            tagtoendings[line[0]] = endingpairs
        #endfor
        for token in self.tokens:
            if not token.isword:
                continue
            wordform = toascii(token.token)
            iscapital = wordform.istitle()
            wordform = wordform.lower()
            tag = token.tag
            lemma = token.lemma
            if len(set(wordlist.formtoaccenteds.get(wordform,[]))) == 1:
                token.accented = wordlist.formtoaccenteds[wordform][0]
            elif wordform in wordlist.formtotaglemmaaccents:
                candidates = []
                for (lextag, lexlemma, accented) in wordlist.formtotaglemmaaccents[wordform]:
                    casedist = 1 if (iscapital != lexlemma.replace("-","").istitle()) else 0
                    tagdist = postags.tagDist(tag, lextag)
                    lemdist = levenshtein(lemma, lexlemma)
                    if token.startssentence:
                        candidates.append((0,tagdist,lemdist,accented))
                    else:
                        candidates.append((casedist,tagdist,lemdist,accented))
                candidates.sort()
                token.accented = candidates[0][3]
                token.isambiguous = True
            else:
                ## Unknown word, but attempt to mark vowels in ending:
                ## To-do: Better support for different capitalization and orthography
                token.accented = token.token
                if any(i in token.token for i in u"aeiouyAEIOUY"):
                    for (accentedending, plainending) in tagtoendings.get(tag, []):
                        if wordform.endswith(plainending):
                            token.accented = wordform[:-len(plainending)] + accentedending
                            break
                    token.isunknown = True
    #enddef
    def macronize(self, domacronize, alsomaius, performutov, performitoj):
        for token in self.tokens:
            token.macronize(domacronize, alsomaius, performutov, performitoj)
    #enddef
    def detokenize(self, markambiguous):
        def enspancharacters(text):
            result = ""
            for char in text:
                if char in u"āēīōūȳĀĒĪŌŪȲaeiouyAEIOUY":
                    result = result + '<span>'+char+'</span>'
                else:
                    result = result + char
            return result
        #enddef
        result = ""
        enclitic = ""
        for token in self.tokens:
            if token.isreordered:
                enclitic = token.macronized
            else:
                if token.token.lower() == "ne" and len(enclitic) > 0: ## Not nēque...
                    result += token.token + enclitic
                else:
                    unicodetext = postags.unicodeaccents(token.macronized)
                    if markambiguous:
                        unicodetext = enspancharacters(unicodetext)
                        if token.isambiguous:
                            unicodetext = '<span class="ambig">' + unicodetext + '</span>'
                        elif token.isunknown:
                            unicodetext = '<span class="unknown">' + unicodetext + '</span>'
                        else:
                            unicodetext = '<span class="auto">' + unicodetext + '</span>'
                    result += unicodetext + enclitic
                enclitic = ""
        return result
    #enddef
#endclass

class Macronizer:
    def __init__(self):
        self.wordlist = Wordlist()
        self.tokenization = Tokenization("")
    #enddef
    def settext(self, text):
        self.tokenization = Tokenization(text)
        self.wordlist.loadwords(self.tokenization.allwordforms())
        newwordforms = self.tokenization.splittokens(self.wordlist)
        self.wordlist.loadwords(newwordforms)
        self.tokenization.addtags()
        self.tokenization.addlemmas(self.wordlist)
        self.tokenization.getaccents(self.wordlist)
    #enddef
    def gettext(self, domacronize=True, alsomaius=False, performutov=False, performitoj=False, markambigs=False):
        self.tokenization.macronize(domacronize, alsomaius, performutov, performitoj)
        return self.tokenization.detokenize(markambigs)
    #enddef
    def macronize(self, text, domacronize=True, alsomaius=False, performutov=False, performitoj=False, markambigs=False):
        self.settext(text)
        return self.gettext(domacronize, alsomaius, performutov, performitoj, markambigs)
    #enddef
#endclass

if __name__ == "__main__":
    print("""Library for marking Latin texts with macrons. Copyright 2015 Johan Winge.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

Minimal example of usage:
    from macronizer import Macronizer
    macronizer = Macronizer()
    macronizedtext = macronizer.macronize("Iam primum omnium satis constat Troia capta in ceteros saevitum esse Troianos")

Initializing Macronizer() may take a couple of seconds, so if you want
to mark macrons in several strings, you are better off reusing the
same Macronizer object.

The macronizer function takes a couple of optional parameters, which
control in what way the input string is transformed:
    domacronize: mark long vowels; default True
    alsomaius: also mark vowels before consonantic i; default False
    performutov: change consonantic u to v; default False
    performitoj: similarly change i to j; default False
    markambigs: mark up the text in various ways with HTML tags; default False

If you want to transform the same text in different ways, you should use
the separate gettext and settext functions, instead of macronize:
    from macronizer import Macronizer
    macronizer = Macronizer()
    macronizer.settext("Iam primum omnium")
    print(macronizer.gettext())
    print(macronizer.gettext(domacronize=False, performitoj=True))
""")
