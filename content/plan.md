# BYTE: 100 videolik plan

Bu dosya kanalin yol haritasi. Videolar Gemini olmadan, **yazilmis senaryolardan**
uretiliyor: `content/scripts/pNNN-*.json` dosyalari dosya adi sirasiyla alinir
(`tools/pick_script.py`), render edilir, yayinlanir. Siradaki senaryo kalmayinca
daily ~15 saniyede "Kuyruk bos" diye kirmizi durur (Gemini'ye dusmez), yani
**kuyruk bos kalmamali**; kalan 8 ya da daha azsa uyari yazar.

Bu tablo **konu listesi ve ipucu**dur, dogrulanmis bilgi degil. Bir satir senaryoya
donusurken "Dogrulanacak" sutunundaki sayfalar gercekten acilip okunur; sayi ya da
olay dogrulanamazsa o satir dusurulur ya da yedek listeden biriyle degistirilir.
Hicbir sayi buradan videoya kopyalanmaz.

## Her senaryo icin sabit kurallar

- Konu kalici olmali: tarih, olcum ya da kavram. "Bu hafta" haberi yok.
- Her ekran sayisi ya formulle hesaplanir ya da okunmus bir sayfaya baglanir
  (`claims`), her olay iddiasi dosyada kaynak numarasi ve "note" ile durur (`facts`).
- Yasayan ozel kisi adi yok; kurum, sirket ve tarihi kisiler olabilir.
- Hook soru degil, <= 12 kelime. `say` icinde rakam yok, rakam yalniz `cap`te.
- Kapi: `python -m editorial.authored` (CI'da `check.yml` calistirir).

## Yazildi (gun 1-30)

| Gun | Dosya | Bicim | Acilis cumlesi |
|---|---|---|---|
| 1 | `p001-tay-chatbot-under-a-day` | story | Microsoft's chatbot learned from strangers. It lasted under a day. |
| 2 | `p002-gpt3-on-one-gpu` | measured | One graphics card would need two hundred eighty eight years. |
| 3 | `p003-air-canada-chatbot` | story | Air Canada's chatbot gave wrong advice. A tribunal made Air Canada pay. |
| 4 | `p004-one-terabyte-931` | measured | A one terabyte drive can read as nine hundred thirty one gigabytes. |
| 5 | `p005-mechanical-turk` | story | The chess robot that played for an empress had a person inside. |
| 6 | `p006-instructgpt-small-beats-big` | explain | People preferred a model one hundred times smaller than G.P.T. three. |
| 7 | `p007-six-fake-cases` | story | A lawyer asked Chat G.P.T. for cases. Six did not exist. |
| 8 | `p008-whisper-77-years` | measured | Whisper learned from more than seventy seven years of nonstop audio. |
| 9 | `p009-belamy-432500` | story | An algorithm's portrait sold for forty three times its top estimate. |
| 10 | `p010-unix-2038` | measured | In twenty thirty eight, some computers will think it's nineteen oh one. |
| 11 | `p011-eliza-1966` | story | A program from nineteen sixty six imitated a therapist using simple rules. |
| 12 | `p012-one-token-four-characters` | measured | The unit most chatbot prices use is about four characters long. |
| 13 | `p013-deep-blue-1997` | story | A chess machine lost in nineteen ninety six, then won the rematch. |
| 14 | `p014-chatbots-miscount-letters` | explain | Language models write essays, yet struggle to count letters in a word. |
| 15 | `p015-watson-toronto` | story | IBM's quiz machine answered a U.S. cities clue with Toronto. |
| 16 | `p016-seven-billion-parameters-memory` | measured | One model can weigh twenty eight gigabytes or three and a half. |
| 17 | `p017-dartmouth-1956` | story | A two month, ten man study gave artificial intelligence its name. |
| 18 | `p018-what-temperature-does` | explain | Same prompt, same model, and the answer can change every run. |
| 19 | `p019-clever-hans` | story | A horse seemed to do arithmetic. He was reading the humans. |
| 20 | `p020-4k-is-four-1080p` | measured | One four K screen has the pixels of four full H.D. screens. |
| 21 | `p021-alphago-move-37` | story | AlphaGo's move thirty seven had a one in ten thousand chance. |
| 22 | `p022-perceptron-1958` | story | In nineteen fifty eight, a newspaper suggested a machine might walk. |
| 23 | `p023-a-billion-seconds` | measured | A billion seconds is almost thirty two years. |
| 24 | `p024-netflix-prize` | story | Netflix paid one million dollars for an algorithm it did not deploy. |
| 25 | `p025-words-as-coordinates` | explain | King minus man plus woman lands closest to queen, in a model. |
| 26 | `p026-the-speaker-that-laughed` | story | In two thousand eighteen, some Alexa speakers began laughing without being asked. |
| 27 | `p027-24-bit-colour` | measured | A twenty four bit pixel can show sixteen million colors. |
| 28 | `p028-turing-1950-prediction` | story | In nineteen fifty, Turing predicted a test with a five minute limit. |
| 29 | `p029-why-models-hallucinate` | explain | A language model can state a false fact in a confident tone. |
| 30 | `p030-the-context-window` | explain | A chatbot's working memory is a window of fixed size. |

## Siradaki (gun 11-100)

S = hikaye, M = olcum, E = aciklama. Gun numarasi kuyruktaki sirayi gosterir; gunde
1 video ise takvim gunu, gunde 4 video ise dortte biri kadar.

| Gun | Bicim | Konu | Acilis fikri | Dogrulanacak |
|---|---|---|---|---|
| 29 | S | Pasted code, 2023 | A chat window, source code, and a company-wide rule | a reputable report on the memo and the policy response; DROP if only paywalled sources exist |
| 31 | S | The state fair blue ribbon | An image-model entry took first place in 2022 | the fair's results page and news coverage; the category and prize |
| 32 | M | IPv4 against IPv6 | Two to the 32nd against two to the 128th | RFC 791 and RFC 8200; arithmetic |
| 34 | E | Training versus inference | One costs a cluster, the other costs a request | use the GPT-3 figures already verified in day 2; provider docs for the definitions |
| 35 | S | Eugene Goostman | A claimed Turing test pass in 2014 | the organizer's announcement, the percentage, and researchers' objections |
| 36 | M | The genome on a USB stick | 3.1 billion bases at two bits each | NHGRI for the base-pair count; arithmetic |
| 37 | S | Attention Is All You Need | Eight GPUs and three and a half days | the paper's training section: hardware, time, and the benchmark it reports |
| 38 | E | Attention in one minute | Every word asks the others for context | the paper; no claims about any one product |
| 39 | S | The hiring tool that learned the wrong thing | A recruiting model scrapped in 2018 | Reuters report and the company's response; what exactly it penalized |
| 40 | M | Chess against Go | Ten to the 120th against ten to the 170th | Shannon 1950; Tromp's count of legal Go positions; an estimate of atoms in the universe, labeled as an estimate |
| 41 | S | The bots that 'invented a language' | What the 2017 negotiation paper actually showed | the research paper and a fact-check; separate what happened from what headlines said |
| 42 | E | RLHF in three steps | Demonstrate, rank, optimize | the InstructGPT paper already read for day 6 |
| 43 | S | A home-buying algorithm, 2021 | A company let a model bid on houses, then shut the program | the company's earnings statements; dates and the stated size of the write-down |
| 44 | M | CD audio | 44,100 samples, 16 bits, two channels | the CD audio format description; arithmetic to bits per second |
| 45 | S | Ada Lovelace's note, 1843 | She said the machine can only do what it is told | the text of her Note G from a library or museum; paraphrase, do not quote more than 15 words |
| 46 | E | Gradient descent | Walking downhill without a map | a textbook definition; a one-variable worked example |
| 47 | S | Checkers, solved | Eighteen years of computing to prove a draw | the 2007 Science paper and the University of Alberta's account |
| 48 | M | 0.1 plus 0.2 | The most famous rounding error in computing | the Python documentation on floating point; IEEE 754 double precision |
| 49 | S | Google Flu Trends | A search-based forecast that overshot | Lazer et al., Science 2014, and Google's own explanation |
| 50 | E | Quantization | Rounding a model smaller | a framework doc; arithmetic from day 16 |
| 51 | S | The Lighthill report, 1973 | One report that cooled research funding | the report and the BBC debate as documented by a university or archive |
| 52 | M | Apollo's computer | Its memory, counted in kilobytes | NASA or MIT documentation of the guidance computer's memory; arithmetic |
| 53 | S | Samuel's checkers, 1959 | A program that learned by playing itself | Samuel's 1959 paper; where the term 'machine learning' appears |
| 54 | E | Prompt injection | Instructions hiding inside the data | the OWASP LLM Top 10 entry; one harmless illustration |
| 55 | M | ENIAC | Tons, tubes, and additions per second | Smithsonian or Penn archive figures; arithmetic against a phone |
| 56 | S | A robot with a passport | A humanoid robot was granted citizenship in 2017 | the announcement as reported by major outlets, plus expert criticism |
| 57 | E | Diffusion models | Learning to remove noise, one step at a time | Ho et al. 2020; an honest one-line description of what is added and removed |
| 58 | M | ImageNet | Over a million labeled photos and a thousand classes | the ILSVRC dataset page; arithmetic |
| 59 | S | AlexNet, 2012 | The error rate that restarted a field | the AlexNet paper and the ILSVRC 2012 results |
| 60 | E | What a GPU does | Thousands of small calculators at once | vendor documentation; ties to day 2 |
| 61 | S | AlphaZero against Stockfish | Twenty eight wins and no losses, with an asterisk | the AlphaZero paper and the engine developers' objections |
| 62 | M | Chinchilla | Parameters against tokens | Hoffmann et al. 2022 for the model size and token count; arithmetic |
| 63 | S | AlphaFold | A prediction contest and a Nobel | CASP14 results and nobelprize.org |
| 64 | E | Overfitting | Memorizing the exam instead of the subject | a textbook; a tiny polynomial example |
| 65 | M | UTF-8 | One to four bytes per character | RFC 3629; byte counts for a letter, a symbol and an emoji |
| 66 | S | A site bans machine answers | A programming Q and A site paused AI answers in December 2022 | the site's own policy post |
| 67 | E | Open weights, not open source | What you can and cannot do with a downloaded model | the open source definition and the license text of one named model |
| 68 | M | The birthday paradox | 23 people and a coin flip | arithmetic; ties to hash collisions |
| 69 | S | Machine-written finance articles | A newsroom ran AI-written explainers and issued corrections | the publication's own editor's note and a trade-press report |
| 70 | E | Benchmark contamination | When the test was in the textbook | a published contamination study |
| 71 | M | Frames in a Short | Thirty frames a second for sixty seconds | the platform's spec page; arithmetic |
| 72 | S | Forty five minutes in 2012 | A trading firm's software bug | the SEC order; the stated loss and duration |
| 73 | E | Chain of thought | Why 'think step by step' changes the answer | Wei et al. 2022 |
| 74 | M | Moore's law | From a few thousand transistors to billions | the Intel 4004 documentation; a recent chip's published count; no 'newest' claims |
| 75 | S | The Pentium division bug | A chip that got a rare division wrong, 1994 | Intel's account and the researcher's own notes; the stated cost |
| 76 | E | Retrieval-augmented generation | Look it up, then write | Lewis et al. 2020 |
| 77 | S | Beating a Dota 2 world champion team | A five-agent system, 2019 | OpenAI's own post and the match record |
| 78 | M | New York to London | The speed of light sets the floor on latency | the distance and the speed of light in fiber; arithmetic |
| 79 | E | Fine-tuning versus prompting | Two ways to change behavior | provider documentation |
| 80 | S | The service named after the chess robot | Amazon's crowd work marketplace, 2005 | Amazon's launch material; ties back to day 5 |
| 81 | M | A million tokens in novels | How many books fit in a context window | Project Gutenberg word counts for named books; the token ratio from day 12 |
| 82 | E | Scaling laws | More compute and data, smoother loss | Kaplan et al. 2020; avoid any prediction |
| 83 | S | The first computer bug | A moth in a relay, 1947 | the Smithsonian's record of the logbook page |
| 84 | M | How big is a screenshot | Pixels times bytes per pixel | arithmetic and a format description |
| 85 | S | SHRDLU, 1970 | A program that talked about blocks, and why it did not scale | Winograd's own description |
| 86 | E | One neuron in three lines | Multiply, add, squash | a textbook; a worked example with small numbers |
| 87 | M | Parameters in a tiny network | 784 inputs, 128 hidden units, 10 outputs | the MNIST dataset page for the image size; arithmetic |
| 88 | S | The 2024 physics Nobel | Foundations of neural networks win a physics prize | nobelprize.org |
| 89 | E | Bias in training data | A model repeats its dataset | the hiring-tool story from day 39 and one research paper |
| 90 | M | Seconds in a year | 31,536,000, and the leap-year fuzz | arithmetic; the definition of a Julian year |
| 91 | S | Reward hacking: the looping boat | An agent scored points by never finishing the race | OpenAI's 2016 write-up |
| 92 | M | Reading GPT-3's training text | Hundreds of billions of tokens at a human reading speed | day 2's verified token count; a stated reading speed assumption; arithmetic |
| 93 | S | A demo error and a share price | A launch demo with one wrong answer, February 2023 | Reuters; the stated market value change |
| 94 | E | A model file is a list of numbers | What is inside a weights file | arithmetic from day 16; a framework doc |
| 95 | S | Hide-and-seek agents | Agents that exploited the physics engine | OpenAI's 2019 post and paper |
| 96 | M | ASCII | 128 characters in seven bits | the ASCII standard; arithmetic |
| 97 | S | The Breakout tunnel | An agent found a strategy its authors had not planned for | the 2015 Nature paper or DeepMind's write-up |
| 98 | E | Images as tokens | How a picture becomes 'words' | the Vision Transformer paper |
| 99 | S | A million users in five days | A chatbot's first week, late 2022 | the company's statement as reported by major outlets |
| 100 | M | 100 days of BYTE | The channel's own totals, from its own ledger | built from the repo's ledger at day 100: videos, minutes of runtime, frames drawn |

## Yedek (bir satir dogrulanamazsa yerine)

| Bicim | Konu | Acilis fikri | Dogrulanacak |
|---|---|---|---|
| E | The Chinese Room | A thought experiment about understanding | Searle 1980 |
| E | Moravec's paradox | Hard for people is easy for machines, and the reverse | Moravec 1988 as cited by a textbook |
| M | How much information is in English | Bits per letter in Shannon's guessing game | Shannon 1951 |
| E | The Winograd schema | A pronoun test for common sense | Levesque et al. 2012 |
| S | McCulloch and Pitts, 1943 | The first neuron model was logic, not biology | the 1943 paper |
| S | Backpropagation, 1986 | An old idea that finally worked | Rumelhart, Hinton, Williams 1986 |
| S | LeNet and zip codes | A network that read mail in the 1990s | LeCun et al. |
| M | How many photos a phone could hold | Storage arithmetic with a stated assumption | format sizes |

## Dagilim

100 video: 45 hikaye, 30 olcum, 25 aciklama. Ardisik iki
video hic ayni bicimde degil.

## Yeni parti yazarken

1. Siradaki 10 satirin "Dogrulanacak" sayfalarini ac ve oku.
2. `content/scripts/pNNN-<kisa-ad>.json` yaz (alanlar icin README, "Yazilmis senaryo").
3. `python -m editorial.authored` temiz cikmali, sonra `python -m unittest discover -s tests`.
4. Bu dosyada satiri "Yazildi" tablosuna tasi.

