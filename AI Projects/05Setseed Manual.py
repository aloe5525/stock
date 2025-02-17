
import sys
keep_vars = dir(sys.modules['__main__']) # delete all vars except for main variables
for var in list(globals().keys()):
    if var not in keep_vars:
        del globals()[var]
import pathlib
from math import isnan, ceil, exp, sqrt
import pandas as pd
from random import random, seed, SystemRandom
from numpy import corrcoef
from keras.models import Sequential
from keras import layers
import tensorflow as tf
from copy import deepcopy

# original name: Setseed Manual.py
# ai, that takes in ohlc stock data and returns a µ value, indicating how the stocks going to go
# last modified: 3/12/2023

SEED = 1873169

# seed(SEED)
# tf.random.set_seed(SEED)
tf.keras.utils.set_random_seed(SEED)


version = "1.0" 
whatis = "stockpercs-31dconvs-base-relu-0.00001-mse-dropout"

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

file_path = os.path.join(root_dir, "read", "Usable.xlsx") # Usable because more samples
stocklist = pd.read_excel(file_path)["Symbols"] # read only the ticker symbols
del file_path

stocks = stocklist.sort_values().reset_index(drop=True).to_list()
stock_evals = [stocks.pop(len(stocks)-1-x*20) for x in range(len(stocks)//20)] # take out 5% for evaluation
del stocklist

raw = [] # raw y2h stock data
evals = []
comps = ["meanrise"]
scores = [] # will store index of model, end validation loss and how many epochs it took to get there
modelvars = [] # will store initvars for tested models
pres = [] # will store precalculated stock evaluation means
# Samplesize, Layers between, nLayers, Start nFilter, Start Kernel, Dropout, Learning Rate
initvars = [512, 1, 2, 128, 48, 0, 1e-05]
samples = 2048
batchsiz = 32
data = [] # data the ai will train on
y_data = 0 # expected output
y_evals = [] 
time = 0 # global time where data is taken from
epochs = 1000

def randint(low, high): # different random function to improve randomness
    high = int(high + 1)
    low = int(low)
    n = random() # random real number
    for i in range(1, high-low):
        if (n <= i/(high-low)): return i - 1 + low # if max = 4 and min = 0: if 0.2143124 < 1/4: return 0
    return high - 1

def truerandint(low, high): # completely random function (only used for getting next change)
    high = int(high + 1)
    low = int(low)
    n = SystemRandom().random() # random seed
    for i in range(1, high-low):
        if (n <= i/(high-low)): return i - 1 + low # if max = 4 and min = 0: if 0.2143124 < 1/4: return 0
    return high - 1

def read(x): # get 2 year hourly data from 1/20/2023
    pat = os.path.join(root_dir, "read", f"{x}.txt")
    path = pathlib.Path(pat)
    if not path.exists(): 
        return [] # check if file exists in dataset else return empty list
    file = open(path)
    op = []
    lines = file.read() # read the lines
    lins = lines.splitlines() # split lines when \n is present
    for line in lins:
        l = line.split(",") # get values in line by splitting at ","
        a = float(l[3])
        # b = float(l[1])
        # c = float(l[2])
        # d = float(l[3])
        #e = float(l[4]) # exclude volume for now
        if not isnan(a): op.append(a)#, e]) # for shape (75, 3000, 5), also exclude nans
    file.close()
    return op

# if all are loaded ~ 4gb of ram
print("Loading stock data...")
print("")
got = [] # so that one stock isnt loaded twice
runs = 0
temp = []
progress = 1
while runs < samples:
    print("\033[A                                                   \033[A")
    print("Stock: " + str(progress) + "/" + str(len(stock_evals) + samples))
    rn = randint(0, len(stocks)-1)
    while rn in got: 
        rn = randint(0, len(stocks)-1)
    got.append(rn)
    raw.append(read(stocks[rn]))
    if len(raw[-1]) >= initvars[0]+18: # also check whether stock has enough values to be evaluated
        runs += 1
        progress += 1
    else:
        raw.pop(-1)
evals = [] # same as raw but just for evaluation purposes
for s in stock_evals:
    print("\033[A                                                   \033[A")
    print("Stock: " + str(progress) + "/" + str(len(stock_evals) + samples))
    temp = read(s)
    if len(temp) >= initvars[0]+18: # minimum size
        evals.append(temp)
    progress += 1
# for s in stocks:
#     raw.append(read(s))
# evals.append(read(stock_evals))
del stocks, stock_evals, read, s, got, runs, rn, temp, progress # delete unused variables
numsts = len(raw) # how many stocks
#print("Yes I am using the new code")
print("Preloading Dataset...")


def near(a, b, n): # rounds a and b to n digits and checks if they're the same
    return round(a, n) == round(b, n) # if a rounded = b rounded then they're really close

def exp_values(n): # get exponent weights in list
    exps = []
    for i in range(n):
        val = exp(-(4/pow(n, 2))*pow(i+1-(n/4), 2))
        exps.append(val)
    return exps

def mean_rise(stock, spot): # get mean exponential rise from spot
    mu = 0
    if len(stock)-1 >= spot + 16: # make sure there are at least 16 more samples
        weights = exp_values(16)
        for s in range(1, 16):
            if stock[spot+s]-stock[spot] > 0: mu += weights[s] # if value went up when compared to start, add positive weight
            else: mu -= weights[s] # else add negative
        mu /= 16 # get mean
    else: return float("nan")
    return mu

def numtostr(number, roundto=3): # for better readability in the plr files
    if type(number) == int: # if int return normal string
        return str(number)
    number = round(number, roundto) # round so it doesn't get too cluttered
    if number > -1 and number < 1 and number != 0: # if the number is between -1 and 1 and not 0 then we can shorten it to ex. -.5
        if number < 0: return "-" + str(number)[2:] # remove the 0 from the string and add - to beginning
        else: return str(number)[1:]
    return str(number)


def prep_stocks(): # prepare raw data for ai
    global pres
    for i in range(numsts+len(evals)): # for each used stock + evaluation
        pres.append([])
        for j in range(len(comps)):
            pres[-1].append([])
    # get mean rises for stocks
    progress = 1
    print("Stock: " + str(progress) + "/" + str(len(evals) + samples))
    for st in range(len(raw)):
        print("\033[A                                                   \033[A")
        print("Stock: " + str(progress) + "/" + str(len(evals) + samples))
        for pr in range(len(raw[st])):
            pres[st][0].append(mean_rise(raw[st], pr)) # append mean rise for each spot in each stock for evaluation
        for spot in range(len(raw[st])-1): # convert price into percentages | do it from the back
            raw[st][len(raw[st])-1-spot] = -1+2*int(raw[st][len(raw[st])-1-spot]/raw[st][len(raw[st])-2-spot]-1 > 0) # (prnow/prbefore-1 > 0)
        raw[st][0] = -1
        progress += 1
    for st in range(len(evals)):
        print("\033[A                                                   \033[A")
        print("Stock: " + str(progress) + "/" + str(len(evals) + samples))
        for pr in range(len(evals[st])):
            pres[numsts+st][0].append(mean_rise(evals[st], pr))
        for spot in range(len(evals[st])-1): # convert price into percentages | do it from the back
            evals[st][len(evals[st])-1-spot] = -1+2*int(evals[st][len(evals[st])-1-spot]/evals[st][len(evals[st])-2-spot]-1 > 0) # (prnow/prbefore-1 > 0)
        evals[st][0] = -1
        progress += 1
            # maxx = max(pres[st][3]) # save max of rise graph to scale it
            # for r in range(len(pres[st][3])): # scale graph
            #     pres[st][0][r] /= maxx

def inp_fn():
    global data, y_data, time
    index = randint(0, len(raw)-1) # random stock curve
    while len(raw[index]) < initvars[0]+18: # if stock is too short, reroll
        index = randint(0, len(raw)-1)
    stock = raw[index] # simplified
    time = randint(initvars[0], len(stock)-17) # get random end sample
    data = deepcopy(stock[time-initvars[0]:time]) # ohlc graph in percentages in timeframe
    y_data = deepcopy(pres[index][0][time]) # one value for µ at the end of the sample | *ran because percentages double, µ doubles
    return data, y_data

def eval_fn():
    global data, y_data, time
    index = randint(0, len(evals)-1) # random stock curve
    while len(evals[index]) < initvars[0]+18: # if stock is too short, reroll
        index = randint(0, len(evals)-1)
    stock = evals[index]
    time = randint(initvars[0], len(stock)-17) # get random end sample
    data = deepcopy(stock[time-initvars[0]:time]) # ohlc graph in percentages in timeframe
    y_data = deepcopy(pres[numsts+index][0][time]) # one value for µ at the end of the sample
    return data, y_data

prep_stocks()
del prep_stocks, mean_rise, exp_values

# thank the chatgpt here
class StockSeq(Sequential):
    
    def __init__(self, layers=None, name=None):
        super(StockSeq, self).__init__(layers=layers, name=name)

    def train_step(self, data):
        # Generate batchsize random x and y values using the input function
        x_batch = []
        y_batch = []
        for i in range(batchsiz): # pregenerate a batch
            x_data, y_data = inp_fn()
            x_batch.append(x_data)
            y_batch.append(y_data)
        
        x_batch = tf.convert_to_tensor(x_batch)
        y_batch = tf.convert_to_tensor(y_batch)

        with tf.GradientTape() as tape:
            y_pred = self(x_batch, training=True)
            loss = self.compiled_loss(y_batch, y_pred)

        trainable_vars = self.trainable_variables
        gradients = tape.gradient(loss, trainable_vars)
        self.optimizer.apply_gradients(zip(gradients, trainable_vars))

        self.compiled_metrics.update_state(y_batch, y_pred)
        results = {m.name: m.result() for m in self.metrics}
        
        # Update validation metrics
        
        val_x = []
        val_y = []
        for i in range(batchsiz): # pregenerate a batch to validate
            x_data, y_data = eval_fn()
            val_x.append(x_data)
            val_y.append(y_data)
        
        val_x = tf.convert_to_tensor(val_x)
        val_y = tf.convert_to_tensor(val_y)
        val_y = tf.reshape(val_y, [batchsiz, 1])
        with tf.GradientTape() as tape:
            y_pred_val = self(val_x, training=False)
            loss_val = self.compiled_loss(val_y, y_pred_val)

        self.compiled_metrics.update_state(val_y, y_pred_val, sample_weight=tf.zeros_like(val_y))
        val_results = {f'val_{m.name}': m.result() for m in self.metrics}

        return {**results, **val_results}
    
    def fit(self, batch_size=32, epochs=1, verbose=1, # override fit functions, since it doesn't need inputs anymore
            callbacks=None, validation_split=0.0, validation_data=None,
            shuffle=True, class_weight=None, sample_weight=None,
            initial_epoch=0, steps_per_epoch=None,
            validation_steps=None, validation_batch_size=None,
            validation_freq=1, max_queue_size=10, workers=1,
            use_multiprocessing=False):

        # Create dummy inputs for the fit method
        x = tf.ones((batch_size, 1))
        y = tf.ones((batch_size, 1))

        # Train the model using the input function
        return super().fit(x=x, y=y, batch_size=batch_size, epochs=epochs, verbose=verbose,
                            callbacks=callbacks, validation_split=validation_split, validation_data=validation_data,
                            shuffle=shuffle, class_weight=class_weight, sample_weight=sample_weight,
                            initial_epoch=initial_epoch, steps_per_epoch=steps_per_epoch,
                            validation_steps=validation_steps, validation_batch_size=validation_batch_size,
                            validation_freq=validation_freq, max_queue_size=max_queue_size, workers=workers,
                            use_multiprocessing=use_multiprocessing)
    
    def predict(self, x, batch_size=None, verbose=0, steps=None,
                callbacks=None, max_queue_size=10, workers=1,
                use_multiprocessing=False):

        #global y_evals
        x_input = []
        x_k, _ = eval_fn()
        #y_evals.append(_)
        x_input.append(x_k)
        
        x_input = tf.convert_to_tensor(x_input)

        return self.predict_on_batch(x_input)

model = StockSeq()

@tf.function # necessary
def rescale(x):
    LIMIT = 0.5826765700645536 # upper and lower limit of the function
    x = (x+0.15)*2.16 # rescale
    rescaled_x = tf.clip_by_value(x, -LIMIT, LIMIT)
    return rescaled_x

def make_model(): # from no model to compiled model
    global model
    model = StockSeq()
    model.add(layers.InputLayer(input_shape=initvars[0])) # inputlayer
    model.add(layers.Reshape((initvars[0], 1)))
    nlayers = initvars[2]
    nfilters = initvars[3]
    kernels = initvars[4]
    for i in range(nlayers): # for every layer
        model.add(layers.Conv1D(filters=nfilters, kernel_size=kernels, activation="relu")) # add conv, drop and pool
        model.add(layers.Dropout(initvars[5]))
        model.add(layers.MaxPooling1D())
        nfilters = round(nfilters/2) # divide by 2 to get next layer
        kernels = round(kernels/2)
        if kernels < 5: kernels = 5
    model.add(layers.Flatten())
    num = 8/pow(2, -initvars[1]) # so that more neurons per new layer
    for i in range(initvars[1]):
        model.add(layers.Dense(num, activation='linear'))
        num /= 2
    model.add(layers.Dense(1, activation='linear')) # output layer
    model.add(layers.Dense(1, activation=rescale)) # output layer
    model.compile(optimizer=tf.keras.optimizers.Adam(initvars[6]), loss='mse', metrics=['mae'])

make_model()

def dont_clutter(epoch, logs):
    print("\033[A                                                   \033[A", end="\r")
    print("\033[A                                                   \033[A")

callbacks = [tf.keras.callbacks.LambdaCallback(on_epoch_end=dont_clutter)]

seedpair = (0, 100) # (seed, valloss)

ses = deepcopy(SEED)

# Fit the model
while input("Continue? (y/n)\n") != "n":
    # initvars[0] = int(input("Samplesize: "))
    # initvars[1] = int(input("Layers between: "))
    # initvars[2] = int(input("nLayers: "))
    # initvars[3] = int(input("Start nFilter: "))
    # initvars[4] = int(input("Start Kernel: "))
    # initvars[5] = float(input("Dropout: "))
    # initvars[6] = float(input("Learning Rate: "))
    # print("Now running: ", initvars)
    # make_model()

    #model.summary()

    for i in range(2): print("")
    tote = 0
    contin = True
    lastv = 100
    epochs = 1000
    tf.keras.utils.set_random_seed(ses)
    while contin:
        tote += epochs
        if tote == 29000: contin = False # hard cap
        history = model.fit(epochs=epochs, callbacks=callbacks)
        for i in range(2): print("")
        # Get sma 100 500 epochs ago
        vals = history.history["val_mae"][-600:-500]
        slope = 0
        for v in vals:
            slope += v
        slope /= 100
        # get sma 100 now
        vals = history.history["val_mae"][-100:]
        valloss = 0
        for v in vals:
            valloss += v
        valloss /= 100
        if slope-valloss < 0.005 or lastv <= valloss: # if no real change last 500 epochs or if reverse progress
            contin = False
        else: epochs = 1000
        lastv = round(valloss, 2)
    for i in range(2): print("")
    scores.append((len(modelvars), tote, valloss)) # index, nepochs, valloss
    modelvars.append(deepcopy(initvars))
    if valloss < seedpair[1]: seedpair = (ses, valloss)
    ses -= 1
    print("Score: ", scores[-1][1], scores[-1][2])
    for i in range(2): print("")

print(seedpair)

if input("Save this model? (y/n)\n") != "n":
    model.save("AI Models\\Model-" + numtostr(scores[-1][2]) + "_" + str(initvars[0])+ ".h5")
