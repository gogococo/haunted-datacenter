def authorize(command):
    allowed = {("ground", "west"), ("drain", "east"), ("unlock", "crypt")}
    return (command.get("source") == "signed-controller"
            and (command.get("action"), command.get("zone")) in allowed)
