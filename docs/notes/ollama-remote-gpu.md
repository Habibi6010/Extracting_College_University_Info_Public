# Running Ollama on a remote GPU cluster (optional)

Step 2 can use a local/remote Ollama server instead of OpenAI
(`LLM_PROVIDER=ollama`). If your Ollama runs on a GPU node of an HPC cluster,
tunnel it to your machine. Replace `<user>`, `<login-host>`, `<gpu-node>`.

1. SSH to the login node and get a GPU node (SLURM example):
   `srun -p <gpu-partition> -w <gpu-node> --gres=gpu:1 -N 1 -n 1 -c 4 --mem=32GB -t 2:00:00 --pty bash`
2. On the GPU node: `nohup ollama serve > ollama.log 2>&1 &` then `ollama pull mistral-small3.1:24b`
3. From the login node, tunnel to the GPU node:
   `ssh -N -L 11435:127.0.0.1:11434 <gpu-node>`
4. From your machine, tunnel to the login node:
   `ssh -N -L 11434:127.0.0.1:11435 <user>@<login-host>`
5. Test: `curl http://127.0.0.1:11434/api/tags`; the app default `OLLAMA_HOST` already matches.
