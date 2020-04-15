import valve.source.a2s


def main():
    print("TTT:", isServerUp("66.85.80.171", 27015))
    print("Random:", isServerUp("74.91.119.186", 27015))


def getInfo(address, port):
    try:
        with valve.source.a2s.ServerQuerier((address, port)) as server:
            return server.info()
    except valve.source.NoResponseError:
        return None


def getPlayers(address, port):
    try:
        with valve.source.a2s.ServerQuerier((address, port)) as server:
            return server.players()["players"]
    except valve.source.NoResponseError:
        return None


def getPlayerNames(players):
    names = []
    for player in players:
        names.append(player["name"])
    return names


def isServerUp(address, port):
    try:
        with valve.source.a2s.ServerQuerier((address, port)) as server:
            server.info()
            return True
    except valve.source.NoResponseError:
        return False


if __name__ == "__main__":
    main()
