pushd front-app
call npm.cmd install 
call npm.cmd run build
popd
poetry build