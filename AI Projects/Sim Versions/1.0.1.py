import pathlib
from math import isnan, ceil, exp
import pandas as pd
from random import randint
from copy import deepcopy

# last modified 2/20/2023
version = "1.0.1" 

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

file_path = os.path.join(root_dir, "read", "Usable.xlsx")
stocklist = pd.read_excel(file_path)["Symbols"] # read only the ticker symbols
del file_path

stocks = stocklist.sort_values().reset_index(drop=True) # sort the stocks alphabetically so ai doesn't only train on good ones
stock_evals = pd.Series([stocks.pop(i*20) for i in range(stocks.size//20)], name="Symbols") # take out 5% / 1/20 of the dataset to evaluate the ai on (// means floor division)
stocks = stocks.to_list()
stock_evals = stock_evals.to_list()
del stocklist

raw = [] # raw y2h stock data
time = 0 #randint(0, 2000) # random time point
timeframe = 2000 # until when the time is counted (so that stocks with less data wont only appear at the start)
money = 10000 # in dollars
operations = [] # stores the active operations
usedstocks = [] # predefinition

# vars for random cells
avconds = ["up", "down", "movavg", "expavg", "35up", "35down", "engulfup", "engulfdown", "closeabove", "closebelow", "contested"]
comps = ["movavg", "expavg", "contested", "meanrise"] # meanrise not part of conditions just in here fro convenience
pres = [] # will store precalculated complex conditions | shape = (stock, comps, (either 1 or how many of one kind there are), (either len(stock) or similar))
preinds = [] # will store the f.e. windows of the moving averages so: preinds = [[100, 200]]; precalcs[0][0][preinds[0].index(200)]

def read(x): # get 2 year hourly data from 1/20/2023
    pat = os.path.join(root_dir, "read", f"{x}.txt")
    path = pathlib.Path(pat)
    if not path.exists(): 
        return [] # check if file exists in dataset else return empty list
    file = open(path)
    op = []
    # hi = []
    # lo = []
    # cl = []
    # vo = []
    lines = file.read() # read the lines
    lins = lines.splitlines() # split lines when \n is present
    for line in lins:
        l = line.split(",") # get values in line by splitting at ","
        a = float(l[0])
        b = float(l[1])
        c = float(l[2])
        d = float(l[3])
        e = float(l[4])
        if not isnan(a): op.append([a, b, c, d, e]) # for shape (75, 3000, 5), also exclude nans
        # op.append(float(l[0])) # for shape (75, 5, 3000)
        # hi.append(float(l[1]))
        # lo.append(float(l[2]))
        # cl.append(float(l[3]))
        # vo.append(float(l[4]))
    file.close()
    #together = [op, hi, lo, cl, vo] # list of lists that contains all the data for the stock
    return op

# if all are loaded ~ 4gb of ram
print("Loading stock data...")
got = [] # so that one stock isnt loaded twice
runs = 0
while runs < 100:
    rn = randint(0, len(stocks)-1)
    while rn in got:
        rn = randint(0, len(stocks)-1)
    got.append(rn)
    raw.append(read(stocks[rn]))
    if len(raw[-1]) >= 2000: # has to be certain length of timeframes
        runs += 1
    else:
        raw.pop(-1)
evals = [] # same as raw but just for evaluation purposes
for s in stock_evals:
    evals.append(read(s))
del got, runs, rn, stocks, stock_evals, read # delete unused variables

def buyable(index, amnt): # returns whether a stock is able to be bought
    return money >= amnt*raw[index][time][3]

class Operation():
    def __init__(self, stock, number, stlo, tapr): # acts as buy function as well
        global money
        # if fractional shares are allowed: number = float, else number = int
        super().__init__()
        self.running = True
        self.ind = stock
        self.amnt = number
        self.stop = stlo
        self.take = tapr
        self.time = time # save for evaluation purposes
        money -= raw[stock][time][3]*number
    def sell(self): # sells for current market price
        global money
        money += raw[self.ind][time][3]*self.amnt
        self.running = False


def near(a, b, n): # rounds a and b to n digits and checks if they're the same
    return round(a, n) == round(b, n) # if a rounded = b rounded then they're really close

def get_cont_extrs(stock): # gets extremes of a graph to calculate contested areas
    top = stock[0][3] # keep track of top value and if it didn't change add to peaks
    bottom = stock[0][3] # also keep track of bottom
    lasttop = 0 # keeps track of when top was last changed
    lastbottom = 0
    timesuntilextreme = 100
    extremes = [] # spots with peaks or lows
    for i in range(len(stock)):
        if stock[i][3] > top:
            top = stock[i][3]
            lasttop = i
        if stock[i][3] < bottom:
            bottom = stock[i][3]
            lastbottom = i
        if i == lastbottom + timesuntilextreme:
            extremes.append(lastbottom)
            lastbottom = i
            bottom = stock[i][3]
        elif i == lasttop + timesuntilextreme:
            extremes.append(lasttop)
            lasttop = i
            top = stock[i][3]
    return extremes

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
        for s in range(16):
            perc = (stock[spot+s][3]/stock[spot][3]-1)*100 # get percentage
            mu += perc*weights[s] # add weighted values
        mu /= 16 # get mean
    return mu
    # if len(stock)-1 > spot + 16:
    #     last = spot # set it to now
    #     for i in range(16):
    #         if stock[last][3] < stock[spot+i][3]: last = spot+i # look if it is larger than
    #     return stock[last][3] > stock[spot][3] # if a rise is present


def condition(index, shape, spot, ma=200, iseval=False):
    # 0 open | 1 high | 2 low | 3 close | 4 volume
    if iseval: stock = evals[index] # evaluation
    else: stock = raw[index] # makes it simpler
    if shape == "up" or shape == "green": # close > open
        return stock[spot][3] > stock[spot][0]
    elif shape == "down" or shape == "red": # close < open
        return stock[spot][3] < stock[spot][0]
    elif shape == "movavg": # will always look for bigger so true means avg > close
        if spot <= ma: return False
        if ma in preinds[0] and not iseval: # if data was precalculated
            slope = pres[usedstocks.index(index)][0][preinds[0].index(ma)][spot]
        else:
            temp = pd.DataFrame(stock[spot-ma:spot])
            slope = temp.rolling(window=ma).mean()[3][ma-1]
        return slope > stock[spot][3]
    elif shape == "expavg":
        if spot <= ma: return False
        if ma in preinds[1] and not iseval: # if precalculated
            slope = pres[usedstocks.index(index)][1][preinds[1].index(ma)][spot]
        else:
            temp = pd.DataFrame(stock[spot-ma:spot])
            slope = temp.ewm(span=ma, adjust=False).mean()[3][ma-1]
        return slope > stock[spot][3]
    elif shape == "35up": # Fibonacci candle up # buying pressure
        # if stock[spot][3] < stock[spot][0]: # if close < open: end || color does not matter
        #     return False
        high = stock[spot][1]
        low = stock[spot][2]
        if stock[spot][3] > stock[spot][0]: body = stock[spot][0]
        else: body = stock[spot][3]
        fibonacci = high - (high - low) * 0.382
        return body > fibonacci
        # temp = stock[spot][1] + stock[spot][2]
        # if stock[spot][3] > stock[spot][0]: lower = stock[spot][0]
        # else: lower = stock[spot][3]
        # return lower >= (1-0.382) * temp # if body of candle in 38.2% of top
    elif shape == "35down": # Fibonacci candle down # selling pressure
        # if stock[spot][0] < stock[spot][3]: # if open < close: end || color does not matter
        #     return False
        #temp = (stock[spot][0]-stock[spot][2])/(stock[spot][1]-stock[spot][2]) # (open-low)/(high-low)
        high = stock[spot][1]
        low = stock[spot][2]
        if stock[spot][3] > stock[spot][0]: body = stock[spot][3]
        else: body = stock[spot][0]
        fibonacci = low + (high - low) * 0.382
        return body < fibonacci
        # temp = stock[spot][1] + stock[spot][2]
        # if stock[spot][3] < stock[spot][0]: upper = stock[spot][0]
        # else: upper = stock[spot][3]
        # print(upper, (1-0.382) * temp)
        # return upper <= 0.382 * temp # if body of candle in 38.2% of bottom
    elif shape == "engulfup": # candle engulfs last and color change # buying pressure
        if stock[spot][0] > stock[spot][3] or stock[spot-1][3] > stock[spot-1][0]: # if opennow > closenow or closelast > openlast: end
            return False
        if not near(stock[spot][0], stock[spot-1][3], 1): # if not open ~~ last close: end
            return False
        return stock[spot][3] > stock[spot-1][0] # close > last open
    elif shape == "engulfdown": # candle engulfs last and color change # selling pressure
        if stock[spot][3] > stock[spot][0] or stock[spot-1][0] > stock[spot-1][3]: # if closenow > opennow or openlast > closelast: end
            return False
        if not near(stock[spot][3], stock[spot-1][0], 1): # if not close ~~ last open: end
            return False
        return stock[spot][3] < stock[spot-1][0] # close < last open
    elif shape == "closeabove": # close is above last high # buying pressure
        return stock[spot][3] > stock[spot-1][1] # close > last high
    elif shape == "closebelow": # close is below last low # selling pressure
        return stock[spot][3] < stock[spot-1][2] # close > last low
    elif shape == "contested": # if many peaks were in same area # market change
        if index in preinds[2] and not iseval:
            extremes = pres[usedstocks.index(index)][2][0] # if precalculated
            for e in extremes:
                if e > spot-100: # if extreme exceeds spot -100 because it needs to have at least 100 values until its considered an extreme
                    exind = extremes.index(e)
                    if exind < 0: # if no extremes until point; give empty list
                        extremes = []
                    else:
                        extremes = extremes[:exind] # only get until last extreme
                    break
        else:
            extremes = get_cont_extrs(stock[:spot-101]) # get extremes until spot
        nbox = []
        contestability = 3 # if contestability values are in nbox then its contested
        for n in range(11): # 5 up 5 down + same
            nbox.append(round(stock[spot][3]-5+n, 0))
        c = 0
        for e in extremes:
            if round(stock[e][3]) in nbox:
                c += 1
        return c >= contestability # if 5 or more peaks/lows are in current area
    elif shape == "bollinger": # bollinger bands
        # risk ranking through this + price envelopes (looser)
        # trend lines (tangents)
        # triangle trend lines
        # resistance line
        # sks formation
        # m w lines
        # leverage banking
        return False
    else:
        print(shape + " is not a shape.\nCheck your writing!")
        return False

class Cell():
    def __init__(self, condit, timespot, spvar=200):
        super().__init__()
        self.condition = condit
        self.spot = timespot # usually negative or 0
        self.ma = spvar
        self.active = None
        self.weight = 1 # will only be used in player
    def calculate(self, st, iseval=False):
        global time
        if time + self.spot < 0: # if spot requested is outside of range
            self.active = False
        else:
            self.active = condition(st, self.condition, time+self.spot, self.ma, iseval=iseval)

class Player(): # player that will do the buying
    def __init__(self, is_rand=True, cellnum= 1, readstr=""):
        super().__init__()
        self.cells = [] # cells that contain the conditions
        self.weight = 1 # weight for confidence calculation | basic values
        self.bias = 0
        self.confidence = 0 # same as activation | goal: confidence ~ amount, sl, tp
        self.outs = [1, 0.97, 1.03] # amount, stop loss, take profit
        self.outws = [0, 0, 0] # weights for outs (calc ex: stop = outs[1]+outws[1]*confidence)
        self.average = 0 # will keep track of average money gained using this method
        self.score = 0 # will keep track of rises it has predicted
        if is_rand: # generate random cells
            for i in range(cellnum):
                inco = randint(0, len(avconds)-1) # index of choosen condition
                spt = -i # spot of condition (for first generation pick -i)
                m = randint(2, 300) # time range for averages
                self.cells.append(Cell(avconds[inco], spt, m))
                #self.weight = 1 + randint(-5, 5)/10
                #self.bias = randint(-10, 10)/10
        elif readstr != "":
            split = readstr.split("+")
            ncells = int(split[0]) # get number of cells
            split = split[1].split("%") # get rest of string and split cells
            for sp in split:
                if len(sp) > 0: # so no empty cells exist
                    tings = sp.split("/")
                    self.cells.append(Cell(tings[0], int(tings[1]), int(tings[2])))
    def calc(self, index, iseval=False):
        global operations, money
        if len(self.cells) == 0: # if the Player has no cells, i.e. no conditions
            return None
        numerator = 0 # how many times true is seen
        denominator = 0 # how many conditions/cells there are
        for c in self.cells: # calculate cell activations
            denominator += 1
            c.calculate(index, iseval=iseval)
            if c.active: numerator += 1
        self.confidence = (numerator/denominator) * self.weight + self.bias
        if self.confidence >= 1: # if confidence of 1 or more: buy
            nvec = []
            for i in range(3):
                nvec.append(self.outs[i]+self.outws[i]*self.confidence) # calculate buy order based on confidence
            nvec[0] = int(nvec[0]) # make amount an integer
            if iseval: price = evals[index][time][3] # current price
            else: price = raw[index][time][3] # current price
            if (buyable(index, nvec[0])): operations.append(Operation(index, nvec[0], price*nvec[1], price*nvec[2])) # if enough money is available; buy
    def mutate(self, mode, cel=Cell("up", -31)):
        if mode == 0: # add / new
            rangee = 1
            for i in range(3): # makes range random so that changes in upper/lower parts are more unlikely
                rangee *= pow(2, randint(0, 1))
                if i == 2: rangee *= pow(2, randint(-1, 1)) # so that curve focuses more on lower numbers
            rangee = int(rangee) # if range = 2^-1 | range distribution: 1:5, 2:7, 4:7, 8:4, 16:1
            if randint(1, 50) == 1: # so that 32 is technically possible
                rangee *= 2
            spot = -randint(0, rangee)
            rem = -1
            for cell in self.cells:
                if cell.spot == spot:
                    rem = self.cells.index(cell) # look if cell exists in spot already
            if rem != -1:
                self.cells.pop(rem) # remove cell
            inco = randint(0, len(avconds)-1) # condition
            m = randint(1, 300) # time range for averages
            self.cells.append(Cell(avconds[inco], spot, m))
        elif mode == 1: # remove
            if len(self.cells) > 0:
                rem = randint(0, len(self.cells)-1) # pick random cell
                self.cells.pop(rem) # remove cell
        elif mode == 2: # add / replace with given cell
            rem = -1
            for cell in self.cells:
                if cell.spot == cel.spot: 
                    rem = self.cells.index(cell) # look if cell exists in spot already
            if rem != -1:
                self.cells.pop(rem) # remove cell
            self.cells.append(cel) # add replacement cell
        elif mode == 3: # small changes
            ran = randint(0, len(self.cells)-1)
            choose = randint(0, 2)
            if choose == 0: # spot change
                self.cells[ran].spot += randint(-5, 5) 
                if self.cells[ran].spot > 0: self.cells[ran].spot = 0
                rem = -1
                i = 0
                for cell in self.cells:
                    if cell.spot == self.cells[ran].spot and i != ran:
                        rem = self.cells.index(cell) # look if cell exists in spot already
                    i += 1
                if rem != -1:
                    self.cells.pop(rem) # remove cell
            elif choose == 1: # value change
                ran = randint(0, len(self.cells)-1)
                self.cells[ran].ma += randint(-50, 50)
                if self.cells[ran].ma <= 1:
                    self.cells[ran].ma = 2
            else: # weight / bias change
                self.weight += randint(-5, 5)/20
                self.bias += randint(-5, 5)/20
    def reset(self):
        self.average = 0
        self.score = 0
    def savestring(self):
        save = "" # should be num cells, seperated by commas
        save += str(len(self.cells)) + "+" # + is basic seperator
        for i in range(len(self.cells)):
            save += self.cells[i].condition + "/" # / is seperator for values
            save += str(self.cells[i].spot) + "/"
            save += str(self.cells[i].ma) + "/%" # % is seperator for cells
        return save

def cellcomp(c1, c2): # compares if 2 cells are the same
    if c1.condition != c2.condition: return False # if conditions don't match
    if c1.spot != c2.spot: return False # if spot doesn't match
    if c1.condition in ["movavg", "expavg"]: # ma check | only for ones that actually matter
        if c1.ma != c2.ma: return False
    return True


def same(pl1, pl2): # looks if 2 players are the same
    if len(pl1.cells) != len(pl2.cells): return False # different amount of cells
    for c in range(len(pl1.cells)):
        if not cellcomp(pl1.cells[c], pl2.cells[c]): return False # if cells don't match up
    if pl1.weight != pl2.weight: return False # if weights don't match up
    if pl1.bias != pl2.bias: return False # if biases don't match up
    if pl1.outws != pl2.outws: return False # if order weights don't match up
    return True

def remove_clones(players): # removes duplicate players and returns player list
    newp = players
    remlist = []
    cont = True
    while cont:
        for p in range(len(newp)):
            for pl in range(len(newp)):
                if p != pl and same(newp[p], newp[pl]): # checks if two players are the same
                    remlist.append(pl)
                if len(remlist) > 0: break
            if len(remlist) > 0: break
            if p == len(newp)-1: cont = False # if every player has been checked
        for r in remlist:
            newp.pop(r) # remove players
        remlist = []
    return newp

players = []
plnum = 20 # number of players
gens = 10 # number of generations
for i in range(plnum):
    players.append(Player())
usedstocks = [] # what stocks are used in a generation
numsts = 10 # how many stocks
for i in range(numsts):
    rn = randint(0, len(raw)-1)
    while rn in usedstocks: # not to get same stock twice
        rn = randint(0, len(raw)-1)
    usedstocks.append(rn) # dependent on how many stocks are preloaded
del rn

# make precalc pre lists
for i in range(numsts): # for each used stock
    pres.append([])
    for j in range(len(comps)): # complex conditions: ["movavg", "expavg", "contested", "meanrise"]
        pres[-1].append([])
for j in range(len(comps)):
    preinds.append([])

# get mean rises for stocks
for st in usedstocks:
    maxx = 0 # save max of rise graph to scale it
    for pr in range(len(raw[st])):
        pres[usedstocks.index(st)][3].append(mean_rise(raw[st], pr)) # append mean rise for each spot in each stock for evaluation
        if maxx < pres[usedstocks.index(st)][3][-1]: maxx = pres[usedstocks.index(st)][3][-1]
    for r in range(len(pres[usedstocks.index(st)][3])): # scale graph
        pres[usedstocks.index(st)][3][r] /= maxx
del st, pr, maxx

def precalculate(plrs): # precalculate complex functions such as moving averages and save them in memory
    global preinds, pres
    for p in plrs: # plrs is players
        for c in p.cells:
            if c.condition in comps: # if condition is a complex function
                tc = comps.index(c.condition) # get index of condition
                if tc < 2: # lower indexes are averages so there are more of them
                    if not c.ma in preinds[tc]: # if moving average has not yet been calculated
                        preinds[tc].append(c.ma) # append to precalculated indexes
                        for st in usedstocks:
                            temp = pd.DataFrame(raw[st])
                            if tc == 0: avg = temp.rolling(window=c.ma).mean()[3].reset_index(drop=True).to_list() # get list of moving average
                            else: avg = temp.ewm(span=c.ma, adjust=False).mean()[3].reset_index(drop=True).to_list() # exp. mov. avg.
                            pres[usedstocks.index(st)][tc].append(avg) # add average to precalcs
                elif tc == 2: # contested areas
                    for st in usedstocks:
                        if not st in preinds[tc]:
                            preinds[tc].append(st)
                            pres[usedstocks.index(st)][tc].append(get_cont_extrs(stock=raw[st])) # get extremes of stock and append them to precalcs


def timestep(stock, player, iseval=False):
    global time, operations, players
    time += 1
    poplist = [] # operations that have finished
    if iseval: # for evaluation purposes
        for op in operations:
            if evals[stock][time][3] <= op.stop: # if stop loss is reached
                op.sell()
                poplist.append(operations.index(op))
            elif evals[stock][time][3] >= op.take: # if take profit is reached
                op.sell()
                poplist.append(operations.index(op))
        poplist.reverse() # reverse list, so that later indexes are removed first
        for p in poplist: # remove finished operations
            operations.pop(p)
        # player maths
        player.calc(stock, iseval=True) # player execution
    else:
        for op in operations:
            if raw[op.ind][time][3] <= op.stop: # if stop loss is reached
                op.sell()
                poplist.append(operations.index(op))
            elif raw[op.ind][time][3] >= op.take: # if take profit is reached
                op.sell()
                poplist.append(operations.index(op))
        poplist.reverse() # reverse list, so that later indexes are removed first
        for p in poplist: # remove finished operations
            scr = pres[usedstocks.index(operations[p].ind)][3][operations[p].time]*operations[p].amnt # score (meanrise*orderamnt = score)
            player.score += scr*(raw[stock][0][3]/200) # multiply by price/200 to eliminate smaller stocks being better
            operations.pop(p)
        # player maths
        player.calc(stock) # player execution

def sell_all():
    global operations
    for op in operations:
        op.sell()
    operations = []


hiscores = []
miscores = []
gainhi = []
gainmid = []

evalstock = 0 # index of stock that will be used for evaluation purposes

# generation simulation
print("Starting simulation...")
for g in range(gens):
    print("Preparing new generation...")
    precalculate(players)
    print("Generation " + str(g+1) + "\n")
    start = randint(0, 1000)
    startmoney = 10000
    timeframe = start + 1000
    scores = []
    print("Player 1 -- score:") # filler text that gets deleted afterwards
    print(0)
    for player in players:
        print("\033[A                                                   \033[A")
        print("\033[A                                                   \033[A")
        print("Player " + str(len(scores) + 1) +" -- score:")
        print(0)
        for stock in usedstocks:
            time = start
            money = startmoney
            am200 = int(ceil(200/raw[stock][0][3])) # get the amount for 200 dollars so that each buy costs about the same amnt of money
            player.outs[0] = am200 # set basic amount
            while time < timeframe: # timeframe for stock simulation
                timestep(stock, player)
            sell_all()
            player.average += money-startmoney # add balance change to average
            print("\033[A                                                   \033[A")
            print(player.score)
        # evaluation
        # time = 500 # so that averages exist
        # timeframe = 1000
        # money = 10000
        # am200 = int(ceil(200/evals[evalstock][0][3]))
        # player.outs[0] = am200
        # while time < timeframe:
        #     timestep(evalstock, player, iseval=True)
        # sell_all()
        player.average /= numsts # get average change
        scores.append((players.index(player), player.score, player.average)) # (index, score, gains in $)
    scores = sorted(scores, key=lambda x: x[1])
    scores.reverse()
    print("\nHighscore: " + str(round(scores[0][1], 2)) + " Gains: " + str(round(scores[0][2], 2)) +
    "$\nMidscore: " + str(round(scores[len(players)//2][1], 2)) + " Gains: " + str(round(scores[len(players)//2][2], 2)) +"$")
    hiscores.append(scores[0][1])
    miscores.append(scores[len(players)//2][1])
    gainhi.append(scores[0][2])
    gainmid.append(scores[len(players)//2][2])
    templist = []
    temp  = len(players)
    if g < gens-2: # only mutate if there is a next generation
        print("Advancing to next generation...")
        for t in range(temp//2): # get top 50 % of players
            templist.append(players[scores[t][0]])
        players = templist # set only top 50 % of players
        for p in players: # reset player scores
            p.reset()
        for i in range(temp//2):
            ranpl = randint(0, temp/2-1) # random player to modify
            gen = randint(0, 2) # what to do with player
            if len(players[ranpl].cells) <= 1: # if player has / would have no more cells left, add cell
                gen = 0
            players.append(deepcopy(players[ranpl])) # copy player and place in spot -1
            if gen == 2: # replace
                ranpl2 = randint(0, temp/2-1) # player 2 to take from | also could happen that player mutates with self
                while ranpl2 != ranpl or len(players[ranpl2].cells) == 0:
                    ranpl2 = randint(0, temp/2-1)
                rancell = randint(0, len(players[ranpl2].cells)-1) # pick random cell index
                players[-1].mutate(2, players[ranpl2].cells[rancell]) # replace cell with new one in new player
            else:
                players[-1].mutate(gen)
        players = remove_clones(players) # remove duplicate players
        for i in range(temp-len(players)): # if players were removed
            players.append(Player(cellnum=randint(1, 6))) # fill in new ones with at least 3 cells


# for each in players:
#     print(each.savestring())

file = open("Algorithm Results\\" + version + "_" + str(gens) + "-" + str(plnum)+ ".txt", "w")
file.write("Highscore,Midscore,Gainhigh,Gainmid\n")
for h in range(len(hiscores)):
    file.write(str(hiscores[h]) + "," + str(miscores[h]) + "," + str(gainhi[h]) + "," + str(gainmid[h]) + "\n")
file.close()

file = open("Algorithm Results\\" + version + "_" + str(gens) + "-" + str(plnum)+ ".plr", "w")
for pl in players:
    file.write(pl.savestring() + "\n")
file.close()

print(hiscores)
print(miscores)
print(gainhi)
print(gainmid)

# def sell(index, amnt): # sell amnt stock for current close
#     global money, hold
#     if amnt <= hold:
#         hold -= amnt
#         money += amnt*raw[index][time][3]
#     return False

# def strategy():
#     nt = timeframe-time # new time so that shorter stocks appear at the end
#     nt *= -1 # index form
#     for i in range(len(raw)):
#         if len(raw[i]) >= -1 * nt: # nt will be time taken from the end and not beginning so if the stock has too little we skip it
#             if time >= 200:
#                 temp = pd.DataFrame(raw[i][nt-200:nt])
#                 #print(temp)
#                 slope = temp.rolling(window=200).mean()[3][199] # get rolling average for 10 days
#                 if slope > raw[i][nt][3] and money > raw[i][nt][3]: # if cond and money available
#                     buy(i, 1) # buy stocks
#                 elif slope <= raw[i][nt][3] and hold != 0:
#                     sell(i, 1)

# for j in range(11):
#     file = open("Data\\Data" + str(j) + ".txt", "w")
#     for c in conds[j]:
#         file.write(str(c) + ",\n")
#     file.close()

# if hold > 0:
#     money += raw[0][timeframe-time][3]*hold
#     hold = 0

# print(money)

# inp = input("Action?\n")

# while inp != "break":
#     if inp == "time":
#         time += 1
#     elif inp == "buy":
#         inp = int(input("How many?\n"))
#         hold += inp
#         money -= inp*raw[0][time][3]
#         print("Bought " + str(inp) + " for " + str(raw[0][time][3]) + " each.")
#         print("New balance: " + str(money))
#     elif inp == "sell":
#         inp = int(input("How many?\n"))
#         hold -= inp
#         money += inp*raw[0][time][3]
#         print("Sold " + str(inp) + " for " + str(raw[0][time][3]) + " each.")
#         print("New balance: " + str(money))
#     elif inp == "balance":
#         print(money)
#     elif inp == "price":
#         print(raw[0][time][3])
#     inp = input("Action?\n")

