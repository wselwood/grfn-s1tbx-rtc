$WORKINGPATH=(Get-Item -Path ".\").FullName + ":/output"
docker pull asfdaac/s1tbx-rtc

$command="& docker run -it -v " + ($WORKINGPATH) + " --rm asfdaac/s1tbx-rtc " + $args
iex $command
