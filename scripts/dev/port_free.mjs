// Decide whether a TCP port is free for a server that will bind `host`.
//
// Two independent checks, because neither alone is sufficient:
//
//  1. Bind the address the server itself will bind. A guard that binds
//     `127.0.0.1` while the server binds `::` (or the reverse) answers about a
//     different socket than the one the launch needs.
//  2. Connect to the loopback addresses. On macOS a listener on `::` does not
//     prevent a later bind of `127.0.0.1`, so check (1) alone reported "free"
//     for a port an unrelated process was already answering on — the launcher
//     then declared the demo ready over a foreign server's response.
//
// Exit 0 when the port is free, 1 when it is taken, 2 for a usage error.
import net from "node:net";

const port = Number(process.argv[2]);
const host = process.argv[3] || "127.0.0.1";

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  console.error(`port_free: not a usable TCP port: ${process.argv[2]}`);
  process.exit(2);
}

function canBind() {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen({ port, host, ipv6Only: false }, () => server.close(() => resolve(true)));
  });
}

function answers(address) {
  return new Promise((resolve) => {
    let settled = false;
    const socket = net.connect({ port, host: address });
    const done = (value) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(1000, () => done(false));
    socket.once("connect", () => done(true));
    socket.once("error", () => done(false));
  });
}

const bindable = await canBind();
if (!bindable) {
  console.error(`port_free: ${host}:${port} cannot be bound`);
  process.exit(1);
}
for (const address of ["127.0.0.1", "::1"]) {
  if (await answers(address)) {
    console.error(`port_free: something is already answering on [${address}]:${port}`);
    process.exit(1);
  }
}
process.exit(0);
