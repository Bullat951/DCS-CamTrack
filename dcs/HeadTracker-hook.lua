-- HeadTracker-hook.lua - Head Tracker -> DCS cockpit view, no TrackIR / opentrack / driver.
-- Installed by the Head Tracker app into Saved Games\DCS\Scripts\Hooks.
--
-- The app sends the head pose as text over UDP 127.0.0.1:4245:
--     HTK1 <seq> <active 0|1> <yaw> <pitch> <roll> <x> <y> <z>     (values -1..1 of each axis)
-- Every frame the newest packet is applied with Export.LoSetCommand to DCS's six "Absolute Camera"
-- axis commands (ids are global, the same in every aircraft - read from the user's binding files).
-- Paused or no fresh packet: nothing is sent, so DCS's own mouse look works.
-- Once a second a status line goes back to UDP 127.0.0.1:4246 for the app.

local HTK_VERSION = '1.0.0'
local IDS = { 2010, 2011, 2047, 2049, 2051, 2053 }   -- yaw, pitch, roll, x (side), y (up), z (fore/aft)
local IN_PORT, OUT_PORT = 4245, 4246
local STALE_S = 0.3

local H = { sock = nil, out = nil, active = false, last = 0, vals = nil, sent = 0, lastStatus = 0,
            errLogged = {}, wasApplying = false }

local function L(msg) pcall(log.write, 'HEADTRACK', log.INFO, msg) end
local function once(key, msg) if not H.errLogged[key] then H.errLogged[key] = true; L(msg) end end

local function open()
    if H.sock then return true end
    package.path = package.path .. ';.\\LuaSocket\\?.lua'
    package.cpath = package.cpath .. ';.\\LuaSocket\\?.dll'
    local ok, socket = pcall(require, 'socket')
    if not ok or not socket then once('socket', 'LuaSocket not available: ' .. tostring(socket)); return false end
    local s = socket.udp()
    s:settimeout(0)
    local okb, err = s:setsockname('127.0.0.1', IN_PORT)
    if not okb then once('bind', 'cannot listen on ' .. IN_PORT .. ': ' .. tostring(err)); s:close(); return false end
    local o = socket.udp()
    o:settimeout(0)
    o:setpeername('127.0.0.1', OUT_PORT)
    H.sock, H.out = s, o
    L('listening on 127.0.0.1:' .. IN_PORT)
    return true
end

local function drain(now)
    local newest
    for _ = 1, 64 do                       -- a few packets per frame at most; keep only the newest
        local data = H.sock:receive()
        if not data then break end
        newest = data
    end
    if not newest then return end
    local seq, act, a, b, c, d, e, f = newest:match('^HTK1 (%d+) ([01]) (%S+) (%S+) (%S+) (%S+) (%S+) (%S+)')
    if not seq then once('fmt', 'bad packet: ' .. newest:sub(1, 60)); return end
    H.active = act == '1'
    H.vals = { tonumber(a), tonumber(b), tonumber(c), tonumber(d), tonumber(e), tonumber(f) }
    H.last = now
end

local function apply()
    for i, id in ipairs(IDS) do
        local v = H.vals[i]
        if v then
            if v > 1 then v = 1 elseif v < -1 then v = -1 end
            Export.LoSetCommand(id, v)
        end
    end
    H.sent = H.sent + 1
end

local function status(now)
    if now - H.lastStatus < 1.0 then return end
    H.lastStatus = now
    local okU, unit = pcall(DCS.getPlayerUnitType)
    pcall(H.out.send, H.out, string.format('HTKS %s %s %d %d', HTK_VERSION,
        (okU and unit and unit ~= '') and unit or '-', H.wasApplying and 1 or 0, H.sent))
end

local cb = {}

function cb.onSimulationStart()
    H.sent, H.wasApplying = 0, false
    open()
end

function cb.onSimulationFrame()
    local ok, err = pcall(function()
        if not open() then return end
        local now = DCS.getRealTime()
        drain(now)
        local applying = H.vals ~= nil and H.active and (now - H.last) < STALE_S
        if applying then apply() end
        if applying ~= H.wasApplying then
            L(applying and 'head tracking ON' or 'head tracking OFF (mouse look free)')
            H.wasApplying = applying
        end
        status(now)
    end)
    if not ok then once('frame', 'frame error: ' .. tostring(err)) end
end

function cb.onSimulationStop()
    L(string.format('mission ended, %d frames applied', H.sent))
end

DCS.setUserCallbacks(cb)
L('HeadTracker hook ' .. HTK_VERSION .. ' loaded')
