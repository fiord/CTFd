CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;
    const md = _CTFd.lib.markdown();

    // Populate form fields with existing challenge data
    const challenge_data = CTFd._internal.challenge.data;
    if (challenge_data && challenge_data.type_data.id === "endpoint") {
        $("#docker_image").val(challenge_data.docker_image || "");
    }
});
