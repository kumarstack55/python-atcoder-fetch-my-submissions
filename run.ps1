cd atcoder-submissions
git pull
cd ..

poetry run python ./fetch.py --debug

cd atcoder-submissions
git add .
git commit -m Update
git push
cd ..
