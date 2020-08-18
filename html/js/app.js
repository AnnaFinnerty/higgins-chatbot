console.log('higgins is running')

AWS.config.region = 'us-east-1'; 
AWS.config.credentials = new AWS.CognitoIdentityCredentials({
    IdentityPoolId: '<cognitopoolid>',
});

var lambda = null
var interval = null
const wait = 30
var counter = 0

var params = {
    FunctionName : 'HigginsV2',
    InvocationType : 'RequestResponse',
    LogType : 'None',
    Payload: ''
};
const output = document.querySelector('h1')
const input = document.querySelector('textarea')
input.focus()


document.body.addEventListener('keypress',(e)=>{
    stopResponseTimer()
    if(e.keyCode === 13){
        console.log('ask')
        output.textContent = "";
        output.className = "thinking"
        requestResponse()
    }
})

requestResponse = (text) => {
    if(!lambda){
        lambda = new AWS.Lambda({region: 'us-east-1', apiVersion: '2015-03-31'});
    }
    params['Payload'] = text ? JSON.stringify(text) : JSON.stringify(input.value)
    console.log(params)
    if(!interval){
        //startResponseTimer()
    }
    lambda.invoke(params, function(err, data) {
        if (err) {
            console.log(params)
        } else {
            const results = JSON.parse(data.Payload);
            console.log(results)
            console.log(results.body)
            setTimeout(()=>{
                output.class = ""
                output.textContent = results.body;
                input.value = "";
                output.className = ""
                input.focus()
            },7)
        }
    });
}

startResponseTimer = () => {
    interval = setTimeout(() => {
        console.log(counter)
        if(counter >= 0 && counter < 3){
            counter +=1;
            requestResponse("hello")
        } else {
            stopResponseTimer()
            requestResponse("quit")
        }
    }, 1000);
}
//(15 * (counter+1)) * 1000
stopResponseTimer = () => {
    console.log("STOP")
    clearInterval(interval)
    counter = 0
    interval = null
}
